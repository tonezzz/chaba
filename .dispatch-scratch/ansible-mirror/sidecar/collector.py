#!/usr/bin/env python3
"""
Sidecar metrics collector for Ansible-centralized dispatch.

Runs as a systemd user service on each host. Pushes metrics to Redis (or HTTP endpoint)
every 15s. Designed to be tiny (~100 LOC), no deps beyond stdlib + redis.

Metrics exposed:
- cpu_pct, mem_pct, disk_pct, load1/5/15
- gpu: list of {index, name, mem_used_mb, mem_free_mb, util_pct, temp_c}
- containers: list of {id, name, image, cpu_pct, mem_mb, gpu_ids}
- opencode_serve: {healthy, port, pid}
- hostname, timestamp, tags (static: gpu, idc, laptop, etc.)
"""

import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Config ──────────────────────────────────────────────────────────────
INTERVAL_SEC = int(os.getenv("SIDECAR_INTERVAL", "15"))
REDIS_URL = os.getenv("SIDECAR_REDIS_URL", "redis://localhost:6379/0")
HTTP_ENDPOINT = os.getenv("SIDECAR_HTTP_ENDPOINT")  # alternative: POST JSON here
HOSTNAME = os.getenv("SIDECAR_HOSTNAME") or socket.gethostname()
TAGS = os.getenv("SIDECAR_TAGS", "").split(",") if os.getenv("SIDECAR_TAGS") else []

# Static tags from inventory groups
if "idc" in HOSTNAME or HOSTNAME.startswith("idc"):
    TAGS.append("idc")
if "omen" in HOSTNAME:
    TAGS.append("gpu")
if "macbook" in HOSTNAME:
    TAGS.append("laptop")
if "con01" in HOSTNAME:
    TAGS.append("server")


# ─── Helpers ─────────────────────────────────────────────────────────────
def run(cmd: List[str], timeout: int = 5) -> Optional[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return None


def read_file(path: str) -> Optional[str]:
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


# ─── Collectors ──────────────────────────────────────────────────────────
def collect_cpu_mem() -> Dict[str, float]:
    # /proc/stat for CPU, /proc/meminfo for memory (Linux)
    # Fallback to psutil-like logic via shell if needed
    out = {}
    if sys.platform == "linux":
        # CPU: user+nice+system+idle+iowait+irq+softirq+steal
        stat = read_file("/proc/stat")
        if stat:
            first = stat.splitlines()[0].split()
            if first[0] == "cpu":
                vals = list(map(int, first[1:8]))
                total = sum(vals)
                idle = vals[3] + vals[4]
                # We'll track delta between calls for percentage
                out["_cpu_raw"] = (total, idle)
        mem = read_file("/proc/meminfo")
        if mem:
            for line in mem.splitlines():
                if line.startswith("MemTotal:"):
                    out["mem_total_kb"] = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    out["mem_avail_kb"] = int(line.split()[1])
    return out


def collect_load() -> Dict[str, float]:
    if sys.platform == "linux":
        load = read_file("/proc/loadavg")
        if load:
            parts = load.split()
            return {"load1": float(parts[0]), "load5": float(parts[1]), "load15": float(parts[2])}
    return {}


def collect_disk() -> Dict[str, float]:
    out = {}
    if sys.platform == "linux":
        df = run(["df", "-B1", "/"])
        if df:
            lines = df.splitlines()
            if len(lines) > 1:
                parts = lines[1].split()
                total = int(parts[1])
                used = int(parts[2])
                out["disk_total_b"] = total
                out["disk_used_b"] = used
                out["disk_pct"] = (used / total) * 100 if total else 0
    return out


def collect_gpu() -> List[Dict[str, Any]]:
    """Query nvidia-smi for GPU metrics. Returns [] if no NVIDIA GPU or nvidia-smi missing."""
    gpus = []
    out = run(["nvidia-smi", "--query-gpu=index,name,memory.used,memory.free,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"])
    if not out:
        return gpus
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 6:
            gpus.append({
                "index": int(parts[0]),
                "name": parts[1],
                "mem_used_mb": int(parts[2]),
                "mem_free_mb": int(parts[3]),
                "util_pct": int(parts[4]),
                "temp_c": int(parts[5]),
            })
    return gpus


def collect_containers() -> List[Dict[str, Any]]:
    """Get running containers (podman/docker) with resource usage."""
    containers = []
    # Try podman first, then docker
    for runtime in ["podman", "docker"]:
        out = run([runtime, "ps", "--format", "json"])
        if out:
            for line in out.splitlines():
                try:
                    c = json.loads(line)
                    containers.append({
                        "id": c.get("Id", "")[:12],
                        "name": c.get("Names", ""),
                        "image": c.get("Image", ""),
                        "runtime": runtime,
                    })
                except Exception:
                    pass
            break
    # Enrich with stats (non-blocking, best effort)
    for c in containers:
        stats_out = run([c["runtime"], "stats", "--no-stream", "--format", "json", c["id"]], timeout=3)
        if stats_out:
            try:
                s = json.loads(stats_out)
                c["cpu_pct"] = float(s.get("CPUPerc", "0%").rstrip("%"))
                c["mem_mb"] = float(s.get("MemUsage", "0MiB / 0MiB").split("/")[0].replace("MiB", "").strip())
            except Exception:
                pass
    return containers


def collect_opencode_serve() -> Dict[str, Any]:
    """Check if opencode-serve systemd user unit is healthy."""
    out = {}
    # Check systemd user unit
    status = run(["systemctl", "--user", "is-active", "opencode-serve"])
    out["active"] = status == "active"
    # Check port
    port = 4096
    import socket as sock
    s = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
    s.settimeout(1)
    out["port_open"] = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    # Get PID
    pid_out = run(["systemctl", "--user", "show", "opencode-serve", "--property=MainPID"])
    if pid_out:
        try:
            out["pid"] = int(pid_out.split("=")[1])
        except Exception:
            pass
    return out


def collect_static() -> Dict[str, Any]:
    """One-time static facts."""
    return {
        "hostname": HOSTNAME,
        "fqdn": socket.getfqdn(),
        "os": platform.system(),
        "os_version": platform.release(),
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "tags": list(set(TAGS)),  # dedupe
    }


# ─── Main Loop ───────────────────────────────────────────────────────────
def main():
    import redis

    r = redis.from_url(REDIS_URL, decode_responses=True)
    static_facts = collect_static()
    last_cpu = None

    print(f"[sidecar] Starting on {HOSTNAME}, tags={static_facts['tags']}, redis={REDIS_URL}", flush=True)

    while True:
        start = time.time()
        metrics = {"timestamp": start, "hostname": HOSTNAME, "tags": static_facts["tags"], "cpu_count": static_facts["cpu_count"]}

        # CPU/Memory (delta-based for CPU%)
        cpu_mem = collect_cpu_mem()
        if "_cpu_raw" in cpu_mem and last_cpu:
            total_delta = cpu_mem["_cpu_raw"][0] - last_cpu[0]
            idle_delta = cpu_mem["_cpu_raw"][1] - last_cpu[1]
            if total_delta > 0:
                metrics["cpu_pct"] = round((1 - idle_delta / total_delta) * 100, 1)
        if "_cpu_raw" in cpu_mem:
            last_cpu = cpu_mem["_cpu_raw"]
        if "mem_total_kb" in cpu_mem and "mem_avail_kb" in cpu_mem:
            metrics["mem_total_mb"] = round(cpu_mem["mem_total_kb"] / 1024, 1)
            metrics["mem_used_mb"] = round((cpu_mem["mem_total_kb"] - cpu_mem["mem_avail_kb"]) / 1024, 1)
            metrics["mem_pct"] = round((1 - cpu_mem["mem_avail_kb"] / cpu_mem["mem_total_kb"]) * 100, 1)

        # Load
        metrics.update(collect_load())

        # Disk
        metrics.update(collect_disk())

        # GPU
        gpus = collect_gpu()
        if gpus:
            metrics["gpus"] = gpus
            metrics["gpu_count"] = len(gpus)
            metrics["gpu_mem_free_mb"] = sum(g["mem_free_mb"] for g in gpus)
            metrics["gpu_mem_total_mb"] = sum(g["mem_used_mb"] + g["mem_free_mb"] for g in gpus)

        # Containers
        containers = collect_containers()
        if containers:
            metrics["containers"] = containers
            metrics["container_count"] = len(containers)

        # OpenCode serve
        oc = collect_opencode_serve()
        if oc:
            metrics["opencode_serve"] = oc

        # Push to Redis (hash per host, with TTL)
        key = f"sidecar:{HOSTNAME}"
        r.hset(key, mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in metrics.items()})
        r.expire(key, INTERVAL_SEC * 3)  # TTL = 3 intervals

        # Also publish to channel for real-time consumers
        r.publish("sidecar:metrics", json.dumps(metrics))

        elapsed = time.time() - start
        sleep_time = max(0, INTERVAL_SEC - elapsed)
        time.sleep(sleep_time)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[sidecar] Stopped", flush=True)
    except Exception as e:
        print(f"[sidecar] Fatal: {e}", file=sys.stderr, flush=True)
        sys.exit(1)