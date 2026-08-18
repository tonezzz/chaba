import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

REPO_PATH = os.environ.get("REPO_PATH", "/repo")
FRIGATE_URL = os.environ.get("FRIGATE_URL", "http://tony-omen:5000")
SENSOR_READER_URL = os.environ.get("SENSOR_READER_URL", "http://tony-omen:8001")
CAMERAS_JSON = os.path.join(REPO_PATH, "stacks", "nvr", "cameras.json")


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


def sensor_payload() -> dict[str, Any]:
    try:
        r = httpx.get(f"{SENSOR_READER_URL}/api/sensors", timeout=10.0)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        return {"error": str(e)}
    return {"error": "sensor reader unavailable"}


app = FastAPI(title="Status Data API")

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


@app.get("/api/status")
def status() -> dict[str, Any]:
    sensors = sensor_payload()
    return {
        "system": sensors.get("system"),
        "host": sensors.get("host"),
        "git": git_info(),
        "containers": sensors.get("containers"),
        "frigate": frigate_info(),
        "cameras": camera_summary(),
        "gpu": sensors.get("gpu"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/container/{name}")
def container_health(name: str) -> Any:
    try:
        r = httpx.get(f"{SENSOR_READER_URL}/api/container/{name}", timeout=5.0)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Container {name} not found")
        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sensor reader unavailable: {e}")


@app.get("/api/turbo")
def get_turbo() -> Any:
    try:
        r = httpx.get(f"{SENSOR_READER_URL}/api/turbo", timeout=5.0)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sensor reader unavailable: {e}")


class TurboState(BaseModel):
    no_turbo: bool


@app.post("/api/turbo")
def set_turbo(state: TurboState) -> Any:
    try:
        r = httpx.post(f"{SENSOR_READER_URL}/api/turbo", json=state.model_dump(), timeout=5.0)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sensor reader unavailable: {e}")


@app.get("/api/gpu/status")
def get_gpu_status() -> Any:
    try:
        r = httpx.get(f"{SENSOR_READER_URL}/api/gpu/status", timeout=5.0)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sensor reader unavailable: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
