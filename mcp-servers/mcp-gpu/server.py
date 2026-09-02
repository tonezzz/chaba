#!/usr/bin/env python3
"""mcp-gpu — FastMCP controller for GPU job preemption on tony-omen."""
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-gpu")

LLAMA_COMPOSE = os.environ.get(
    "LLAMA_COMPOSE", "/home/tony/CascadeProjects/chaba/stacks/web/docker-compose.yml"
)
LLAMA_URL = os.environ.get("LLAMA_URL", "http://localhost:8001")
if LLAMA_URL == "http://localhost:8008":
    LLAMA_URL = "http://localhost:8001"

IMAGEN_URL = os.environ.get(
    "IMAGEN_URL", "http://localhost:8080/apps/imagen2/api"
)

ORIGINAL_LAYERS: str | None = None


def _run(
    cmd: list[str], check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, env=env)


def _get(url: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, payload: dict, timeout: int = 10) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _docker_compose(*args: str) -> list[str]:
    return ["docker", "compose", "-f", LLAMA_COMPOSE, *args]


def _get_llama_layers() -> str:
    """Read --n-gpu-layers from the running llama container command."""
    try:
        proc = _run(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .Config.Cmd}}",
                "thai-legal-inference",
            ],
            check=False,
        )
        cmd = json.loads(proc.stdout.strip())
        if "--n-gpu-layers" in cmd:
            idx = cmd.index("--n-gpu-layers") + 1
            if idx < len(cmd):
                return cmd[idx]
    except Exception:
        pass
    return "auto"


def _set_llama_layers(layers: str) -> subprocess.CompletedProcess:
    """Recreate llama-server with the requested n_gpu_layers value."""
    env = {**os.environ, "LLAMA_N_GPU_LAYERS": layers}
    return _run(
        _docker_compose("up", "-d", "--force-recreate", "thai-legal-inference"),
        check=False,
        env=env,
    )


@mcp.tool()
def gpu_status() -> str:
    """Return GPU VRAM and compute process summary."""
    result = {"gpus": [], "processes": [], "error": None}
    try:
        proc = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ]
        )
        for line in proc.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                result["gpus"].append(
                    {
                        "name": parts[0],
                        "memory_total_mb": int(float(parts[1])),
                        "memory_used_mb": int(float(parts[2])),
                        "memory_free_mb": int(float(parts[3])),
                    }
                )
    except Exception as exc:
        result["error"] = f"nvidia-smi gpu query failed: {exc}"

    try:
        proc = _run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ]
        )
        for line in proc.stdout.strip().splitlines():
            if line.lower().startswith("no running"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                result["processes"].append(
                    {
                        "pid": parts[0],
                        "name": parts[1],
                        "memory_used_mb": int(float(parts[2])),
                    }
                )
    except Exception as exc:
        result["error"] = f"nvidia-smi process query failed: {exc}"

    return json.dumps(result, indent=2)


@mcp.tool()
def hold_llama(timeout: int = 60) -> str:
    """Move llama-server to CPU (n_gpu_layers=0) and wait until /health is reachable."""
    global ORIGINAL_LAYERS
    ORIGINAL_LAYERS = _get_llama_layers()
    if ORIGINAL_LAYERS == "0":
        return json.dumps({"status": "llama already on cpu", "original_layers": ORIGINAL_LAYERS})
    _set_llama_layers("0")
    url = f"{LLAMA_URL.rstrip('/')}/health"
    end = time.time() + timeout
    while time.time() < end:
        try:
            _get(url, timeout=2)
            return json.dumps({"status": "llama on cpu", "original_layers": ORIGINAL_LAYERS})
        except Exception:
            pass
        time.sleep(1)
    return json.dumps(
        {"status": "error", "message": f"llama /health not reachable after {timeout}s"}
    )


@mcp.tool()
def resume_llama(timeout: int = 120) -> str:
    """Restore llama-server to its original n_gpu_layers and wait until /health is reachable."""
    target = ORIGINAL_LAYERS if ORIGINAL_LAYERS is not None else _get_llama_layers()
    if target in (None, "0"):
        target = "auto"
    _set_llama_layers(target)
    url = f"{LLAMA_URL.rstrip('/')}/health"
    end = time.time() + timeout
    while time.time() < end:
        try:
            _get(url, timeout=2)
            return json.dumps({"status": "llama restored", "gpu_layers": target})
        except Exception:
            pass
        time.sleep(1)
    return json.dumps(
        {"status": "error", "message": f"llama /health not reachable after {timeout}s"}
    )


@mcp.tool()
def generate_image(
    prompt: str,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 512,
    steps: int = 4,
    seed: int = 42,
    guidance_scale: float = 1.0,
    guidance_rescale: float = 0.0,
    mode: str = "lightning_txt2img",
    output_path: str = "/tmp/mcp-gpu-test.png",
    timeout: int = 300,
) -> str:
    """Hold llama, run an imagen2 generation, save the PNG, and resume llama."""
    start = time.time()
    held_result = json.loads(hold_llama())
    if held_result.get("status") == "error":
        return json.dumps({"success": False, "error": "failed to hold llama"})

    try:
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "seed": seed,
            "guidance_scale": guidance_scale,
            "guidance_rescale": guidance_rescale,
            "mode": mode,
        }
        base = IMAGEN_URL.rstrip("/")
        resp = _post(f"{base}/generate", payload, timeout=10)
        job_id = resp.get("job_id")
        if not job_id:
            return json.dumps({"success": False, "error": "no job_id from imagen2"})

        poll_url = f"{base}/progress/{job_id}"
        end = time.time() + timeout
        job = {}
        while time.time() < end:
            job = _get(poll_url, timeout=10)
            if job.get("done"):
                if job.get("error"):
                    return json.dumps(
                        {"success": False, "error": job["error"], "job_id": job_id}
                    )
                break
            time.sleep(2)

        if not job.get("done"):
            return json.dumps(
                {
                    "success": False,
                    "error": "imagen2 generation timed out",
                    "job_id": job_id,
                }
            )

        result = job.get("result") or {}
        image_b64 = result.get("image_base64", "")
        if not image_b64:
            return json.dumps(
                {
                    "success": False,
                    "error": "no image in imagen2 response",
                    "job_id": job_id,
                }
            )

        out = Path(output_path)
        out.write_bytes(base64.b64decode(image_b64))
        duration = round(time.time() - start, 2)

        return json.dumps(
            {
                "success": True,
                "job_id": job_id,
                "image_path": str(out.resolve()),
                "image_size_bytes": out.stat().st_size,
                "seed": result.get("seed"),
                "inference_time": result.get("inference_time"),
                "total_time": duration,
                "llama_held": held_result,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})
    finally:
        try:
            resume_llama()
        except Exception:
            pass


if __name__ == "__main__":
    mcp.run(transport="stdio")
