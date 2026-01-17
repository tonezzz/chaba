from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field

import torch

try:
    from diffusers import SanaPipeline
except Exception:  # pragma: no cover
    SanaPipeline = None  # type: ignore


APP_NAME = "mcp-sana"
APP_VERSION = "0.1.0"

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
_log = logging.getLogger(APP_NAME)

PORT = int(os.getenv("PORT", "8069"))
MCP_SANA_INSTANCE_ID = os.getenv("MCP_SANA_INSTANCE_ID", f"mcp-sana-{uuid.uuid4().hex[:8]}")

MCP_SANA_MODEL_ID = (os.getenv("MCP_SANA_MODEL_ID") or "Efficient-Large-Model/Sana_600M_512px_diffusers").strip()
MCP_SANA_DEVICE = (os.getenv("MCP_SANA_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")).strip()

def _default_dtype_raw() -> str:
    if MCP_SANA_DEVICE.startswith("cuda") and torch.cuda.is_available() and torch.cuda.device_count() > 0:
        try:
            major, _minor = torch.cuda.get_device_capability(0)
        except Exception:
            major = 0
        return "bf16" if major >= 8 else "fp16"
    return "fp32"

_MCP_SANA_DTYPE_RAW = (os.getenv("MCP_SANA_DTYPE") or _default_dtype_raw()).strip().lower()
if _MCP_SANA_DTYPE_RAW in ("bf16", "bfloat16"):
    MCP_SANA_DTYPE = torch.bfloat16
elif _MCP_SANA_DTYPE_RAW in ("fp16", "float16"):
    MCP_SANA_DTYPE = torch.float16
else:
    MCP_SANA_DTYPE = torch.float32

_log.info("sana_config device=%s dtype=%s model=%s", MCP_SANA_DEVICE, _MCP_SANA_DTYPE_RAW, MCP_SANA_MODEL_ID)

MCP_SANA_MAX_PIXELS = int(os.getenv("MCP_SANA_MAX_PIXELS", str(1024 * 1024)))
MCP_SANA_MAX_DIMENSION = int(os.getenv("MCP_SANA_MAX_DIMENSION", "1024"))
MCP_SANA_MAX_STEPS = int(os.getenv("MCP_SANA_MAX_STEPS", "60"))
MCP_SANA_DEFAULT_STEPS = int(os.getenv("MCP_SANA_DEFAULT_STEPS", "20"))
MCP_SANA_MAX_CONCURRENT_JOBS = int(os.getenv("MCP_SANA_MAX_CONCURRENT_JOBS", "1"))

_executor = ThreadPoolExecutor(max_workers=max(1, MCP_SANA_MAX_CONCURRENT_JOBS))


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Any
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


class SanaJobCreateArgs(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = Field(default=None, alias="negativePrompt")
    width: Optional[int] = None
    height: Optional[int] = None
    num_inference_steps: Optional[int] = Field(default=None, alias="numInferenceSteps")
    guidance_scale: Optional[float] = Field(default=None, alias="guidanceScale")
    seed: Optional[int] = None


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> JsonRpcResponse:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data))


class SanaJobStatusArgs(BaseModel):
    job_id: str = Field(..., alias="jobId")


class SanaJobResultArgs(BaseModel):
    job_id: str = Field(..., alias="jobId")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _encode_png_base64(pil: Image.Image) -> str:
    import base64

    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _clamp_int(value: Optional[int], *, default: int, min_value: int, max_value: int) -> int:
    v = default if value is None else int(value)
    if v < min_value:
        v = min_value
    if v > max_value:
        v = max_value
    return v


def _round_down_multiple(value: int, *, base: int) -> int:
    if base <= 1:
        return int(value)
    v = int(value)
    v -= v % int(base)
    return v


def _validate_sana_args(args: SanaJobCreateArgs) -> Dict[str, Any]:
    prompt = (args.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt_required")

    max_dim = max(256, int(MCP_SANA_MAX_DIMENSION or 1024))
    width = _clamp_int(args.width, default=1024, min_value=256, max_value=max_dim)
    height = _clamp_int(args.height, default=1024, min_value=256, max_value=max_dim)
    width = max(256, _round_down_multiple(width, base=8))
    height = max(256, _round_down_multiple(height, base=8))

    if width * height > int(MCP_SANA_MAX_PIXELS or (1024 * 1024)):
        raise HTTPException(status_code=400, detail=f"too_many_pixels: max={MCP_SANA_MAX_PIXELS}")

    steps = _clamp_int(
        args.num_inference_steps,
        default=int(MCP_SANA_DEFAULT_STEPS or 20),
        min_value=1,
        max_value=max(1, int(MCP_SANA_MAX_STEPS or 60)),
    )

    guidance = float(args.guidance_scale) if args.guidance_scale is not None else 4.5

    return {
        "prompt": prompt,
        "negative_prompt": (args.negative_prompt or None),
        "width": int(width),
        "height": int(height),
        "steps": int(steps),
        "guidance_scale": float(guidance),
        "seed": args.seed,
    }


_sana_pipe: Any = None
_sana_lock = threading.Lock()


def _get_sana_pipeline():
    global _sana_pipe
    if SanaPipeline is None:
        raise RuntimeError("sana_pipeline_unavailable")

    with _sana_lock:
        if _sana_pipe is not None:
            return _sana_pipe

        try:
            torch.set_grad_enabled(False)
        except Exception:
            pass
        try:
            if hasattr(torch.backends, "cudnn"):
                torch.backends.cudnn.benchmark = True
        except Exception:
            pass
        try:
            if hasattr(torch.backends, "cuda") and hasattr(torch.backends.cuda, "matmul"):
                major = 0
                if torch.cuda.is_available() and torch.cuda.device_count() > 0:
                    try:
                        major, _minor = torch.cuda.get_device_capability(0)
                    except Exception:
                        major = 0
                if major >= 8:
                    torch.backends.cuda.matmul.allow_tf32 = True
        except Exception:
            pass

        pipe = SanaPipeline.from_pretrained(MCP_SANA_MODEL_ID, torch_dtype=MCP_SANA_DTYPE)
        pipe.to(MCP_SANA_DEVICE)

        try:
            if hasattr(pipe, "set_progress_bar_config"):
                pipe.set_progress_bar_config(disable=True)
        except Exception:
            pass

        major = 0
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            try:
                major, _minor = torch.cuda.get_device_capability(0)
            except Exception:
                major = 0

        xformers_ok = bool(MCP_SANA_DEVICE.startswith("cuda") and major >= 8)
        if xformers_ok and hasattr(pipe, "enable_xformers_memory_efficient_attention"):
            try:
                pipe.enable_xformers_memory_efficient_attention()
            except Exception:
                xformers_ok = False

        if (not xformers_ok) and hasattr(pipe, "enable_attention_slicing"):
            try:
                pipe.enable_attention_slicing("max")
            except Exception:
                pass

        try:
            if hasattr(pipe, "enable_vae_slicing"):
                pipe.enable_vae_slicing()
        except Exception:
            pass
        try:
            if hasattr(pipe, "enable_vae_tiling"):
                pipe.enable_vae_tiling()
        except Exception:
            pass

        try:
            vae = getattr(pipe, "vae", None)
            if vae is not None:
                pipe.vae.to(dtype=MCP_SANA_DTYPE)
        except Exception:
            pass

        try:
            text_encoder = getattr(pipe, "text_encoder", None)
            if text_encoder is not None:
                pipe.text_encoder.to(dtype=MCP_SANA_DTYPE)
        except Exception:
            pass

        _sana_pipe = pipe
        return pipe


class _SanaJob:
    def __init__(self, *, job_id: str, spec: Dict[str, Any]):
        self.job_id = job_id
        self.spec = spec
        self.created_at_ms = _now_ms()
        self.started_at_ms: Optional[int] = None
        self.finished_at_ms: Optional[int] = None
        self.status = "queued"  # queued|running|succeeded|failed
        self.error: Optional[str] = None
        self.progress = {"step": 0, "steps": int(spec.get("steps") or 0)}
        self.result: Optional[Dict[str, Any]] = None
        self._events: List[Dict[str, Any]] = []
        self._events_cond = threading.Condition()
        self._event_seq = 0

    def add_event(self, event: Dict[str, Any]) -> None:
        with self._events_cond:
            self._event_seq += 1
            payload = {
                "seq": self._event_seq,
                "ts": _now_ms(),
                **event,
            }
            self._events.append(payload)
            self._events_cond.notify_all()

    def wait_for_events(self, *, after_seq: int, timeout_s: float) -> List[Dict[str, Any]]:
        deadline = time.time() + timeout_s
        with self._events_cond:
            while True:
                out = [e for e in self._events if int(e.get("seq") or 0) > after_seq]
                if out:
                    return out
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._events_cond.wait(timeout=remaining)


_jobs: Dict[str, _SanaJob] = {}
_jobs_lock = threading.Lock()


def _create_job(spec: Dict[str, Any]) -> _SanaJob:
    job_id = str(uuid.uuid4())
    job = _SanaJob(job_id=job_id, spec=spec)
    with _jobs_lock:
        _jobs[job_id] = job
    job.add_event({"type": "queued", "jobId": job_id})
    _log.info("job_queued jobId=%s spec=%s", job_id, {k: v for k, v in spec.items() if k != "prompt"})
    return job


def _get_job(job_id: str) -> _SanaJob:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


def _run_job(job: _SanaJob) -> None:
    try:
        job.started_at_ms = _now_ms()
        job.status = "running"
        job.add_event({"type": "started", "jobId": job.job_id})
        _log.info("job_started jobId=%s", job.job_id)

        pipe = _get_sana_pipeline()

        seed = job.spec.get("seed")
        if seed is None:
            seed = int.from_bytes(os.urandom(4), "big")
        generator = torch.Generator(device=MCP_SANA_DEVICE).manual_seed(int(seed))

        steps = int(job.spec.get("steps") or 0)
        job.progress = {"step": 0, "steps": steps}

        autocast_ctx: Any
        if MCP_SANA_DEVICE.startswith("cuda") and torch.cuda.is_available() and MCP_SANA_DTYPE in (torch.float16, torch.bfloat16):
            autocast_ctx = torch.autocast(device_type="cuda", dtype=MCP_SANA_DTYPE)
        else:
            autocast_ctx = contextlib.nullcontext()

        def _cb(_pipe, step_idx: int, _timestep, _kwargs):
            job.progress = {"step": int(step_idx) + 1, "steps": steps}
            job.add_event({"type": "progress", "progress": job.progress})
            return {}

        kwargs: Dict[str, Any] = {
            "prompt": job.spec.get("prompt"),
            "height": int(job.spec.get("height") or 1024),
            "width": int(job.spec.get("width") or 1024),
            "guidance_scale": float(job.spec.get("guidance_scale") or 4.5),
            "num_inference_steps": int(job.spec.get("steps") or 20),
            "generator": generator,
        }
        if job.spec.get("negative_prompt"):
            kwargs["negative_prompt"] = job.spec.get("negative_prompt")

        out = None
        with torch.inference_mode(), autocast_ctx:
            try:
                out = pipe(
                    **kwargs,
                    callback_on_step_end=_cb,
                    callback_on_step_end_tensor_inputs=[],
                )
            except TypeError:
                out = pipe(**kwargs)

        images = None
        if isinstance(out, (list, tuple)) and out:
            images = out
        else:
            images = getattr(out, "images", None)

        if not images:
            raise RuntimeError("no_images")

        pil = images[0]
        if not isinstance(pil, Image.Image):
            raise RuntimeError("invalid_image")

        img_b64 = _encode_png_base64(pil)

        job.result = {
            "model": "sana",
            "modelId": MCP_SANA_MODEL_ID,
            "mimeType": "image/png",
            "imageBase64": img_b64,
            "seed": int(seed),
            "width": int(pil.width),
            "height": int(pil.height),
            "steps": steps,
        }
        job.status = "succeeded"
        job.finished_at_ms = _now_ms()
        job.add_event({"type": "done", "jobId": job.job_id})
        _log.info("job_done jobId=%s", job.job_id)
    except HTTPException as exc:
        job.status = "failed"
        job.error = str(exc.detail)
        job.finished_at_ms = _now_ms()
        job.add_event({"type": "error", "message": job.error})
        _log.warning("job_failed_http jobId=%s error=%s", job.job_id, job.error)
    except RuntimeError as exc:
        msg = str(exc)
        if "out of memory" in msg.lower():
            msg = "cuda_oom"
        job.status = "failed"
        job.error = msg
        job.finished_at_ms = _now_ms()
        job.add_event({"type": "error", "message": job.error})
        _log.warning("job_failed_runtime jobId=%s error=%s", job.job_id, job.error)
    except Exception as exc:
        job.status = "failed"
        job.error = f"unexpected_error: {exc}"
        job.finished_at_ms = _now_ms()
        job.add_event({"type": "error", "message": job.error})
        _log.exception("job_failed_unexpected jobId=%s", job.job_id)
    finally:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


def _snapshot_jobs(limit: int = 50) -> Dict[str, Any]:
    with _jobs_lock:
        jobs = list(_jobs.values())
    jobs.sort(key=lambda j: j.created_at_ms, reverse=True)
    if limit > 0:
        jobs = jobs[: int(limit)]

    counts: Dict[str, int] = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
    items: List[Dict[str, Any]] = []
    for j in jobs:
        counts[j.status] = counts.get(j.status, 0) + 1
        items.append(
            {
                "jobId": j.job_id,
                "status": j.status,
                "progress": j.progress,
                "error": j.error,
                "createdAtMs": j.created_at_ms,
                "startedAtMs": j.started_at_ms,
                "finishedAtMs": j.finished_at_ms,
                "spec": {k: v for k, v in (j.spec or {}).items() if k != "prompt"},
                "events": (j._events[-10:] if isinstance(j._events, list) else []),
            }
        )

    return {"counts": counts, "total": len(jobs), "items": items}


def _snapshot_cuda() -> Dict[str, Any]:
    if not torch.cuda.is_available():
        return {"available": False}
    try:
        free, total = torch.cuda.mem_get_info()
    except Exception:
        free, total = None, None
    return {
        "available": True,
        "device": torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else None,
        "freeBytes": int(free) if free is not None else None,
        "totalBytes": int(total) if total is not None else None,
        "allocatedBytes": int(torch.cuda.memory_allocated()) if hasattr(torch.cuda, "memory_allocated") else None,
        "reservedBytes": int(torch.cuda.memory_reserved()) if hasattr(torch.cuda, "memory_reserved") else None,
    }


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "sana_models",
            "description": "Return Sana model configuration and defaults.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "sana_job_create",
            "description": "Create an image generation job using Sana (diffusers SanaPipeline). Use /sana/jobs/{jobId}/events (SSE) for progress events.",
            "inputSchema": SanaJobCreateArgs.model_json_schema(),
        },
        {
            "name": "sana_job_status",
            "description": "Get status/progress for a Sana image generation job.",
            "inputSchema": SanaJobStatusArgs.model_json_schema(),
        },
        {
            "name": "sana_job_result",
            "description": "Fetch the final result for a completed Sana job (base64 PNG).",
            "inputSchema": SanaJobResultArgs.model_json_schema(),
        },
    ]


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


@app.get("/health")
async def health() -> Dict[str, Any]:
    cuda_ok = bool(torch.cuda.is_available())
    status = "ok" if cuda_ok else "degraded"
    return {
        "status": status,
        "service": APP_NAME,
        "version": APP_VERSION,
        "instanceId": MCP_SANA_INSTANCE_ID,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "cudaAvailable": cuda_ok,
        "device": MCP_SANA_DEVICE,
        "modelId": MCP_SANA_MODEL_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/.well-known/mcp.json")
async def well_known_manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Sana image generation MCP provider (diffusers SanaPipeline).",
        "capabilities": {"tools": tool_definitions()},
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": tool_definitions()}


@app.get("/debug/jobs")
async def debug_jobs(limit: int = 50) -> Dict[str, Any]:
    return _snapshot_jobs(limit=int(limit))


@app.get("/debug/cuda")
async def debug_cuda() -> Dict[str, Any]:
    return _snapshot_cuda()


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args = (payload or {}).get("arguments") or {}

    if tool == "sana_models":
        return {
            "tool": tool,
            "result": {
                "default": "sana",
                "sana": {
                    "modelId": MCP_SANA_MODEL_ID,
                    "dtype": str(MCP_SANA_DTYPE).replace("torch.", ""),
                    "device": MCP_SANA_DEVICE,
                    "maxPixels": MCP_SANA_MAX_PIXELS,
                    "maxSteps": MCP_SANA_MAX_STEPS,
                    "maxConcurrentJobs": MCP_SANA_MAX_CONCURRENT_JOBS,
                },
            },
        }

    if tool == "sana_job_create":
        parsed = SanaJobCreateArgs(**args)
        spec = _validate_sana_args(parsed)
        job = _create_job(spec)
        _executor.submit(_run_job, job)
        return {
            "tool": tool,
            "result": {
                "jobId": job.job_id,
                "status": job.status,
                "eventsUrl": f"/sana/jobs/{job.job_id}/events",
                "statusUrl": f"/sana/jobs/{job.job_id}",
                "resultUrl": f"/sana/jobs/{job.job_id}/result",
            },
        }

    if tool == "sana_job_status":
        parsed = SanaJobStatusArgs(**args)
        job = _get_job(parsed.job_id)
        return {
            "tool": tool,
            "result": {
                "jobId": job.job_id,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
                "createdAtMs": job.created_at_ms,
                "startedAtMs": job.started_at_ms,
                "finishedAtMs": job.finished_at_ms,
            },
        }

    if tool == "sana_job_result":
        parsed = SanaJobResultArgs(**args)
        job = _get_job(parsed.job_id)
        if job.status != "succeeded":
            raise HTTPException(status_code=409, detail=f"job_not_succeeded: {job.status}")
        if not isinstance(job.result, dict):
            raise HTTPException(status_code=502, detail="missing_result")
        return {"tool": tool, "result": {"jobId": job.job_id, **job.result}}

    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


@app.post("/mcp")
async def mcp_endpoint(payload: Dict[str, Any] = Body(...)):
    request = JsonRpcRequest(**(payload or {}))
    if request.id is None:
        return None

    method = (request.method or "").strip()
    params = request.params or {}

    if method == "initialize":
        return JsonRpcResponse(
            id=request.id,
            result={
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "capabilities": {"tools": {}},
            },
        ).model_dump(exclude_none=True)

    if method in ("tools/list", "list_tools"):
        return JsonRpcResponse(id=request.id, result={"tools": tool_definitions()}).model_dump(exclude_none=True)

    if method in ("tools/call", "call_tool"):
        tool_name = (params.get("name") or params.get("tool") or "").strip()
        arguments_raw = params.get("arguments") or {}
        if not tool_name:
            return _jsonrpc_error(request.id, -32602, "Missing tool name").model_dump(exclude_none=True)

        try:
            if tool_name == "sana_models":
                result = {
                    "default": "sana",
                    "sana": {
                        "modelId": MCP_SANA_MODEL_ID,
                        "dtype": str(MCP_SANA_DTYPE).replace("torch.", ""),
                        "device": MCP_SANA_DEVICE,
                        "maxPixels": MCP_SANA_MAX_PIXELS,
                        "maxSteps": MCP_SANA_MAX_STEPS,
                        "maxConcurrentJobs": MCP_SANA_MAX_CONCURRENT_JOBS,
                    },
                }
                return JsonRpcResponse(id=request.id, result=result).model_dump(exclude_none=True)

            if tool_name == "sana_job_create":
                parsed = SanaJobCreateArgs(**(arguments_raw or {}))
                spec = _validate_sana_args(parsed)
                job = _create_job(spec)
                _executor.submit(_run_job, job)
                return JsonRpcResponse(
                    id=request.id,
                    result={
                        "jobId": job.job_id,
                        "status": job.status,
                        "eventsUrl": f"/sana/jobs/{job.job_id}/events",
                        "statusUrl": f"/sana/jobs/{job.job_id}",
                        "resultUrl": f"/sana/jobs/{job.job_id}/result",
                    },
                ).model_dump(exclude_none=True)

            if tool_name == "sana_job_status":
                parsed = SanaJobStatusArgs(**(arguments_raw or {}))
                job = _get_job(parsed.job_id)
                return JsonRpcResponse(
                    id=request.id,
                    result={
                        "jobId": job.job_id,
                        "status": job.status,
                        "progress": job.progress,
                        "error": job.error,
                        "createdAtMs": job.created_at_ms,
                        "startedAtMs": job.started_at_ms,
                        "finishedAtMs": job.finished_at_ms,
                    },
                ).model_dump(exclude_none=True)

            if tool_name == "sana_job_result":
                parsed = SanaJobResultArgs(**(arguments_raw or {}))
                job = _get_job(parsed.job_id)
                if job.status != "succeeded":
                    return _jsonrpc_error(request.id, -32001, f"job_not_succeeded: {job.status}").model_dump(
                        exclude_none=True
                    )
                if not isinstance(job.result, dict):
                    return _jsonrpc_error(request.id, -32001, "missing_result").model_dump(exclude_none=True)
                return JsonRpcResponse(id=request.id, result={"jobId": job.job_id, **job.result}).model_dump(
                    exclude_none=True
                )

        except HTTPException as exc:
            return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
        except Exception as exc:
            return _jsonrpc_error(request.id, -32001, f"error: {exc}").model_dump(exclude_none=True)

        return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'").model_dump(exclude_none=True)

    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'").model_dump(exclude_none=True)


@app.post("/sana/jobs")
async def sana_jobs_create(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    parsed = SanaJobCreateArgs(**(payload or {}))
    spec = _validate_sana_args(parsed)
    job = _create_job(spec)
    _executor.submit(_run_job, job)
    return {
        "jobId": job.job_id,
        "status": job.status,
        "eventsUrl": f"/sana/jobs/{job.job_id}/events",
        "statusUrl": f"/sana/jobs/{job.job_id}",
        "resultUrl": f"/sana/jobs/{job.job_id}/result",
    }


@app.get("/sana/jobs/{job_id}")
async def sana_jobs_status(job_id: str) -> Dict[str, Any]:
    job = _get_job(job_id)
    return {
        "jobId": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "createdAtMs": job.created_at_ms,
        "startedAtMs": job.started_at_ms,
        "finishedAtMs": job.finished_at_ms,
        "eventsUrl": f"/sana/jobs/{job.job_id}/events",
        "statusUrl": f"/sana/jobs/{job.job_id}",
        "resultUrl": f"/sana/jobs/{job.job_id}/result",
    }


@app.get("/sana/jobs/{job_id}/result")
async def sana_jobs_result(job_id: str) -> Dict[str, Any]:
    job = _get_job(job_id)
    if job.status != "succeeded":
        raise HTTPException(status_code=409, detail=f"job_not_succeeded: {job.status}")
    if not isinstance(job.result, dict):
        raise HTTPException(status_code=502, detail="result_missing")
    return job.result


@app.get("/sana/jobs/{job_id}/events")
async def sana_jobs_events(job_id: str, after: int = 0, timeout: float = 20.0):
    job = _get_job(job_id)

    async def _iter():
        last_seq = int(after or 0)
        yield f"event: hello\ndata: {json.dumps({'jobId': job_id, 'after': last_seq})}\n\n"
        while True:
            events = job.wait_for_events(after_seq=last_seq, timeout_s=float(timeout or 20.0))
            if not events:
                yield "event: ping\ndata: {}\n\n"
                continue
            for e in events:
                seq = int(e.get("seq") or 0)
                if seq > last_seq:
                    last_seq = seq
                etype = str(e.get("type") or "message")
                yield f"event: {etype}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                if etype in ("done", "error"):
                    return

    return StreamingResponse(_iter(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
