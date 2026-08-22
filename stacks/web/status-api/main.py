import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import docker
import httpx
import psutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

REPO_PATH = os.environ.get("REPO_PATH", "/repo")
FRIGATE_URL = os.environ.get("FRIGATE_URL", "http://frigate:5000")
CAMERAS_JSON = os.path.join(REPO_PATH, "stacks", "nvr", "cameras.json")

FAN_MAX_TEMP = float(os.environ.get("FAN_MAX_TEMP", "85"))
FAN_RESET_TEMP = float(os.environ.get("FAN_RESET_TEMP", "80"))

TURBO_PATH = Path("/sys/devices/system/cpu/intel_pstate/no_turbo")

def run(*args: str, cwd: str = REPO_PATH) -> str | None:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None

def git_info() -> dict[str, Any]:
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    status = run("git", "status", "--short")
    is_clean = status == "" if status is not None else None
    return {
        "branch": branch,
        "commit": run("git", "rev-parse", "--short", "HEAD"),
        "message": run("git", "log", "-1", "--pretty=%s"),
        "date": run("git", "log", "-1", "--pretty=%ci"),
        "is_clean": is_clean,
    }

def disk_usage(path: str) -> dict[str, Any] | None:
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": path,
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "percent_used": round(usage.used / usage.total * 100, 1),
        }
    except Exception:
        return None

def system_info() -> dict[str, Any]:
    uptime_seconds = 0.0
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
    except Exception:
        pass

    hostname = os.environ.get("HOSTNAME") or os.uname().nodename

    return {
        "hostname": hostname,
        "uptime_seconds": round(uptime_seconds, 1),
        "disk": {
            "repo": disk_usage(REPO_PATH),
            "frigate_storage": disk_usage(os.path.join(REPO_PATH, "frigate", "storage")),
            "outputs": disk_usage(os.path.join(REPO_PATH, "outputs")),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def host_status() -> dict[str, Any]:
    # Initialize psutil CPU percent on first call so subsequent reads are meaningful.
    if not hasattr(host_status, "_cpu_init"):
        psutil.cpu_percent(interval=0.5)
        host_status._cpu_init = True

    memory = psutil.virtual_memory()
    load = psutil.getloadavg()
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)

    temperatures: dict[str, list[dict[str, Any]]] = {}
    fans: dict[str, list[dict[str, Any]]] = {}
    try:
        sensors = psutil.sensors_temperatures()
        preferred = ("coretemp", "k10temp", "cpu_thermal", "acpitz")
        for name in preferred:
            if name in sensors:
                temperatures[name] = [
                    {"label": entry.label or name, "current": entry.current}
                    for entry in sensors[name]
                ]
                break
        if not temperatures and sensors:
            name, entries = next(iter(sensors.items()))
            temperatures[name] = [
                {"label": entry.label or name, "current": entry.current}
                for entry in entries
            ]
    except Exception:
        pass

    try:
        for hwmon_path in Path("/sys/class/hwmon").glob("hwmon*"):
            name = hwmon_path.name
            try:
                name_file = hwmon_path / "name"
                if name_file.exists():
                    name = name_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
            fan_entries = []
            for fan_input in sorted(hwmon_path.glob("fan*_input")):
                match = re.match(r"fan(\d+)_input", fan_input.name)
                if not match:
                    continue
                idx = match.group(1)
                label = f"fan{idx}"
                label_file = hwmon_path / f"fan{idx}_label"
                try:
                    if label_file.exists():
                        label = label_file.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
                try:
                    value = int(fan_input.read_text(encoding="utf-8").strip())
                except Exception:
                    continue
                fan_entries.append({"label": label, "current": value})
            if fan_entries:
                fans[name] = fan_entries
    except Exception:
        pass

    try:
        for chip, entries in psutil.sensors_fans().items():
            chip_fans = fans.setdefault(chip, [])
            for entry in entries:
                chip_fans.append({"label": entry.label or chip, "current": entry.current})
    except Exception:
        pass

    max_temp: float | None = None
    for entries in temperatures.values():
        for entry in entries:
            try:
                v = float(entry["current"])
                if max_temp is None or v > max_temp:
                    max_temp = v
            except Exception:
                continue

    return {
        "cpu_percent": round(cpu_percent, 1),
        "cpu_per_core": [round(x, 1) for x in cpu_per_core],
        "memory": {
            "total_gb": round(memory.total / (1024 ** 3), 2),
            "used_gb": round(memory.used / (1024 ** 3), 2),
            "percent": memory.percent,
        },
        "load_average": {
            "1m": round(load[0], 2),
            "5m": round(load[1], 2),
            "15m": round(load[2], 2),
        },
        "temperatures": temperatures,
        "fans": fans,
        "battery": battery_info(),
        "cpu_freq": cpu_freq_info(),
        "cooling": cooling_info(),
        "fan_control": auto_fan_control(max_temp),
    }


def battery_info() -> dict[str, Any] | None:
    try:
        b = psutil.sensors_battery()
        if b is None:
            return None
        return {
            "percent": b.percent,
            "secsleft": b.secsleft if b.secsleft != -1 else None,
            "power_plugged": b.power_plugged,
        }
    except Exception:
        return None


def cpu_freq_info() -> list[dict[str, Any]]:
    try:
        freqs = psutil.cpu_freq(percpu=True)
        if not freqs:
            return []
        return [
            {"current": f.current, "min": f.min, "max": f.max}
            for f in freqs
        ]
    except Exception:
        return []


def cooling_info() -> dict[str, dict[str, Any]]:
    try:
        result: dict[str, dict[str, Any]] = {}
        for path in Path("/sys/class/thermal").glob("cooling_device*"):
            try:
                name = path.name
                type_ = (path / "type").read_text(encoding="utf-8").strip()
                cur = int((path / "cur_state").read_text(encoding="utf-8").strip())
                max_ = int((path / "max_state").read_text(encoding="utf-8").strip())
                result[name] = {"type": type_, "cur_state": cur, "max_state": max_}
            except Exception:
                continue
        return result
    except Exception:
        return {}


def _hp_hwmon_path() -> Path | None:
    try:
        for p in Path("/sys/class/hwmon").glob("hwmon*"):
            try:
                name = (p / "name").read_text(encoding="utf-8").strip()
                if name in ("hp", "hp-omen", "hp_wmi"):
                    return p
            except Exception:
                continue
    except Exception:
        pass
    return None


def auto_fan_control(max_temp: float | None) -> dict[str, Any]:
    result = {
        "mode": "unknown",
        "max_temp": max_temp,
        "threshold_high": FAN_MAX_TEMP,
        "threshold_low": FAN_RESET_TEMP,
        "action": "none",
    }
    if max_temp is None:
        result["action"] = "no_temp"
        return result
    path = _hp_hwmon_path()
    if path is None:
        result["action"] = "no_hp_hwmon"
        return result
    pwm = path / "pwm1_enable"
    if not pwm.exists():
        result["action"] = "no_pwm1_enable"
        return result
    try:
        current = int(pwm.read_text(encoding="utf-8").strip())
    except Exception as e:
        result["action"] = f"read_error: {e}"
        return result
    # 0 = max, 2 = auto for hp-wmi
    try:
        if max_temp >= FAN_MAX_TEMP and current != 0:
            pwm.write_text("0", encoding="utf-8")
            result["mode"] = "max"
            result["action"] = "set_max"
        elif max_temp <= FAN_RESET_TEMP and current == 0:
            pwm.write_text("2", encoding="utf-8")
            result["mode"] = "auto"
            result["action"] = "set_auto"
        else:
            result["mode"] = "max" if current == 0 else "auto"
            result["action"] = "no_change"
    except Exception as e:
        result["action"] = f"write_error: {e}"
    return result


def container_info() -> list[dict[str, Any]]:
    try:
        client = docker.DockerClient(base_url="unix://var/run/docker.sock")
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            ports = []
            port_bindings = c.attrs.get("HostConfig", {}).get("PortBindings") or {}
            for private, mappings in port_bindings.items():
                if mappings:
                    for m in mappings:
                        host_ip = m.get("HostIp", "")
                        host_port = m.get("HostPort", "")
                        ports.append(f"{host_ip}:{host_port}->{private}" if host_ip else f"{host_port}->{private}")
            result.append({
                "name": c.name,
                "image": c.image.tags[0] if c.image.tags else c.image.id,
                "status": c.status,
                "state": c.attrs.get("State", {}).get("Status", "unknown"),
                "health": c.attrs.get("State", {}).get("Health", {}).get("Status"),
                "ports": ports,
                "started_at": c.attrs.get("State", {}).get("StartedAt"),
                "uptime_seconds": None,
            })
        return result
    except Exception as e:
        return [{"error": f"Docker unavailable: {e}"}]

def frigate_info() -> dict[str, Any]:
    info = {"reachable": False, "version": None, "camera_count": None, "error": None}
    try:
        r = httpx.get(f"{FRIGATE_URL}/api/version", timeout=5.0)
        info["reachable"] = r.status_code == 200
        if r.status_code == 200:
            info["version"] = r.json().get("version") if r.headers.get("content-type", "").startswith("application/json") else r.text.strip()
    except Exception as e:
        info["error"] = str(e)

    try:
        r = httpx.get(f"{FRIGATE_URL}/api/config", timeout=5.0)
        if r.status_code == 200:
            data = r.json()
            cameras = data.get("cameras", {})
            info["camera_count"] = len(cameras)
            info["enabled_count"] = sum(1 for c in cameras.values() if c.get("enabled", True))
    except Exception:
        pass

    return info

def camera_summary() -> dict[str, Any]:
    try:
        with open(CAMERAS_JSON, "r") as f:
            data = json.load(f)
        cameras = data.get("cameras", [])
        groups = data.get("groups", {})
        group_counts = {}
        for c in cameras:
            g = c.get("group", "unknown")
            group_counts[g] = group_counts.get(g, 0) + 1
        return {
            "total": len(cameras),
            "enabled": sum(1 for c in cameras if c.get("enabled")),
            "with_heading": sum(1 for c in cameras if c.get("heading") is not None),
            "groups": {g: {"count": group_counts.get(g, 0), **groups.get(g, {})} for g in groups},
            "sources": dict(sorted(
                {c.get("source"): sum(1 for x in cameras if x.get("source") == c.get("source")) for c in cameras}.items()
            )),
        }
    except Exception as e:
        return {"error": str(e)}

app = FastAPI(title="System Status API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/api/health")
def api_health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/api/container/{name}")
def container_health(name: str):
    """Return health status for a single Docker container by name."""
    try:
        client = docker.DockerClient(base_url="unix://var/run/docker.sock")
        c = client.containers.get(name)
        state = c.attrs.get("State", {})
        health = state.get("Health", {}).get("Status")
        return {
            "name": c.name,
            "status": state.get("Status", "unknown"),
            "health": health,
            "image": c.image.tags[0] if c.image.tags else c.image.id,
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Container {name} not found")


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {
        "system": system_info(),
        "host": host_status(),
        "git": git_info(),
        "containers": container_info(),
        "frigate": frigate_info(),
        "cameras": camera_summary(),
        "gpu": gpu_status(),
    }

class TurboState(BaseModel):
    no_turbo: bool


def _no_turbo_path() -> Path:
    return TURBO_PATH


def read_no_turbo() -> int:
    try:
        return int(_no_turbo_path().read_text(encoding="utf-8").strip())
    except Exception:
        return -1


def write_no_turbo(value: int) -> bool:
    try:
        _no_turbo_path().write_text(str(value), encoding="utf-8")
        return True
    except Exception:
        return False


@app.get("/api/turbo")
def get_turbo() -> dict[str, Any]:
    return {"no_turbo": read_no_turbo()}


@app.post("/api/turbo")
def set_turbo(state: TurboState) -> dict[str, Any]:
    success = write_no_turbo(1 if state.no_turbo else 0)
    return {"no_turbo": read_no_turbo(), "success": success}


def gpu_status() -> dict[str, Any]:
    """Get GPU status using nvidia-smi via docker python library."""
    try:
        client = docker.DockerClient(base_url="unix://var/run/docker.sock")
        
        # Run nvidia-smi in thai-legal-inference container
        container = client.containers.get("thai-legal-inference")
        
        # Get GPU info
        exit_code, output = container.exec_run(
            "nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu --format=csv,noheader,nounits"
        )
        
        stdout = output.decode('utf-8') if output else ""
        lines = stdout.strip().split("\n") if stdout else []
        gpus = []
        for line in lines:
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                gpus.append({
                    "name": parts[0],
                    "memory_total_mb": int(parts[1]),
                    "memory_used_mb": int(parts[2]),
                    "memory_free_mb": int(parts[3]),
                    "utilization_percent": int(parts[4]) if parts[4] else None,
                    "temperature_c": int(parts[5]) if len(parts) > 5 and parts[5] else None,
                })
        
        # Get running processes
        exit_code, output = container.exec_run(
            "nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits"
        )
        
        processes = []
        if output:
            stdout = output.decode('utf-8')
            for line in stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    try:
                        pid = int(parts[0])
                        memory_mb = int(parts[1])
                        # Get process name from host
                        try:
                            proc = psutil.Process(pid)
                            name = proc.name()
                            exe = proc.exe() if proc.exe() else name
                        except Exception:
                            name = f"PID:{pid}"
                            exe = f"PID:{pid}"
                        processes.append({
                            "pid": str(pid),
                            "name": exe,
                            "memory_used_mb": memory_mb,
                        })
                    except Exception:
                        continue
        
        return {
            "gpus": gpus,
            "processes": processes,
            "error": None,
        }
    except Exception as e:
        return {
            "gpus": [],
            "processes": [],
            "error": str(e),
        }


@app.get("/api/gpu/status")
def get_gpu_status() -> dict[str, Any]:
    """Get GPU status including VRAM usage and running processes."""
    return gpu_status()


class GPUAction(BaseModel):
    timeout: int = 60


@app.post("/api/gpu/hold-llama")
def hold_llama(action: GPUAction = GPUAction()) -> dict[str, Any]:
    """Hold llama on CPU - placeholder for MCP integration."""
    return {
        "success": False,
        "message": "Use MCP tool mcp1_hold_llama directly from your IDE",
        "note": "This endpoint requires MCP server integration which is not available in containerized environment",
    }


@app.post("/api/gpu/resume-llama")
def resume_llama(action: GPUAction = GPUAction()) -> dict[str, Any]:
    """Resume llama on GPU - placeholder for MCP integration."""
    return {
        "success": False,
        "message": "Use MCP tool mcp1_resume_llama directly from your IDE",
        "note": "This endpoint requires MCP server integration which is not available in containerized environment",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
