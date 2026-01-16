from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sqlite3
import traceback
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

APP_NAME = "mcp-imagen-light"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8068"))
MCP_CUDA_URL = (os.getenv("MCP_CUDA_URL") or "http://mcp-cuda:8057").strip().rstrip("/")
IMAGES_DIR = (os.getenv("IMAGEN_LIGHT_IMAGES_DIR") or "/data/images").strip()
PUBLIC_BASE_URL = (os.getenv("IMAGEN_LIGHT_PUBLIC_BASE_URL") or f"http://pc1.vpn:{PORT}").strip().rstrip("/")
CLEANUP_HOURS = int(os.getenv("IMAGEN_LIGHT_CLEANUP_HOURS", "24"))
IMAGEN_LIGHT_CUDA_TIMEOUT_SECONDS = float(os.getenv("IMAGEN_LIGHT_CUDA_TIMEOUT_SECONDS", "20"))

IMAGEN_LIGHT_NO_CAPACITY_RETRIES = int(os.getenv("IMAGEN_LIGHT_NO_CAPACITY_RETRIES", "3"))
IMAGEN_LIGHT_NO_CAPACITY_BACKOFF_SECONDS = float(os.getenv("IMAGEN_LIGHT_NO_CAPACITY_BACKOFF_SECONDS", "2"))

IMAGEN_LIGHT_QUEUE_DB_PATH = os.getenv("IMAGEN_LIGHT_QUEUE_DB_PATH", "/data/sqlite/imagen-light.sqlite")
IMAGEN_LIGHT_QUEUE_POLL_SECONDS = float(os.getenv("IMAGEN_LIGHT_QUEUE_POLL_SECONDS", "2"))
IMAGEN_LIGHT_QUEUE_ENABLE = (os.getenv("IMAGEN_LIGHT_QUEUE_ENABLE") or "true").strip().lower() in ("1", "true", "yes", "y", "on")

IMAGEN_LIGHT_MIN_PNG_BYTES = int(os.getenv("IMAGEN_LIGHT_MIN_PNG_BYTES", "2048"))
IMAGEN_LIGHT_MIN_PREVIEW_PNG_BYTES = int(os.getenv("IMAGEN_LIGHT_MIN_PREVIEW_PNG_BYTES", "1"))

os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(os.path.dirname(IMAGEN_LIGHT_QUEUE_DB_PATH) or ".", exist_ok=True)


def _ts_ms() -> int:
    return int(time.time() * 1000)


_queue_conn: Optional[sqlite3.Connection] = None


_UNSET = object()


def _get_queue_conn() -> sqlite3.Connection:
    global _queue_conn
    if _queue_conn is None:
        conn = sqlite3.connect(IMAGEN_LIGHT_QUEUE_DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS imagen_jobs ("
            "job_id TEXT PRIMARY KEY,"
            "created_at_ms INTEGER NOT NULL,"
            "updated_at_ms INTEGER NOT NULL,"
            "status TEXT NOT NULL,"
            "cuda_job_id TEXT NULL,"
            "args_json TEXT NOT NULL,"
            "last_error TEXT NULL,"
            "attempts INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        conn.commit()
        _queue_conn = conn
    return _queue_conn


def _queue_job_create(args: Dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    now = _ts_ms()
    conn = _get_queue_conn()
    conn.execute(
        "INSERT INTO imagen_jobs (job_id, created_at_ms, updated_at_ms, status, cuda_job_id, args_json, last_error, attempts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, now, now, "queued", None, json.dumps(args, ensure_ascii=False, separators=(",", ":")), None, 0),
    )
    conn.commit()
    return job_id


def _queue_job_get(job_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_queue_conn()
    cur = conn.execute(
        "SELECT job_id, created_at_ms, updated_at_ms, status, cuda_job_id, args_json, last_error, attempts FROM imagen_jobs WHERE job_id = ?",
        (job_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "job_id": row[0],
        "created_at_ms": row[1],
        "updated_at_ms": row[2],
        "status": row[3],
        "cuda_job_id": row[4],
        "args_json": row[5],
        "last_error": row[6],
        "attempts": row[7],
    }


def _queue_job_update(
    *,
    job_id: str,
    status: str,
    cuda_job_id: Any = _UNSET,
    last_error: Any = _UNSET,
    attempts: Any = _UNSET,
) -> None:
    conn = _get_queue_conn()
    now = _ts_ms()
    sets: List[str] = ["updated_at_ms = ?", "status = ?"]
    params: List[Any] = [now, status]
    if cuda_job_id is not _UNSET:
        sets.append("cuda_job_id = ?")
        params.append(cuda_job_id)
    if last_error is not _UNSET:
        sets.append("last_error = ?")
        params.append(last_error)
    if attempts is not _UNSET:
        sets.append("attempts = ?")
        params.append(int(attempts))
    params.append(job_id)
    conn.execute(f"UPDATE imagen_jobs SET {', '.join(sets)} WHERE job_id = ?", tuple(params))
    conn.commit()


def _queue_job_next_queued() -> Optional[Dict[str, Any]]:
    conn = _get_queue_conn()
    cur = conn.execute(
        "SELECT job_id, args_json, attempts FROM imagen_jobs WHERE status = 'queued' ORDER BY created_at_ms ASC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        return None
    return {"job_id": row[0], "args_json": row[1], "attempts": int(row[2] or 0)}


async def _queue_worker_loop() -> None:
    if not IMAGEN_LIGHT_QUEUE_ENABLE:
        return
    print("[imagen-light] queue worker loop started", flush=True)
    timeout = httpx.Timeout(IMAGEN_LIGHT_CUDA_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            try:
                item = _queue_job_next_queued()
                if not item:
                    await asyncio.sleep(max(0.5, IMAGEN_LIGHT_QUEUE_POLL_SECONDS))
                    continue

                job_id = str(item.get("job_id") or "").strip()
                attempts = int(item.get("attempts") or 0)
                try:
                    args = json.loads(str(item.get("args_json") or "{}"))
                except Exception:
                    args = {}

                if isinstance(args, dict) and args.get("approved") is None:
                    args["approved"] = True

                attempts += 1
                r = await client.post(f"{MCP_CUDA_URL}/imagen/jobs", json=args)
                if r.status_code >= 400:
                    msg = (r.text or "").strip()
                    if "no_capacity" in msg:
                        _queue_job_update(job_id=job_id, status="queued", last_error=msg[:1000], attempts=attempts)
                        await asyncio.sleep(max(1.0, IMAGEN_LIGHT_NO_CAPACITY_BACKOFF_SECONDS))
                        continue
                    _queue_job_update(job_id=job_id, status="failed", last_error=msg[:1000], attempts=attempts)
                    await asyncio.sleep(max(0.5, IMAGEN_LIGHT_QUEUE_POLL_SECONDS))
                    continue

                meta = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
                cuda_job_id = (meta or {}).get("jobId")
                if not cuda_job_id:
                    _queue_job_update(job_id=job_id, status="failed", last_error="cuda_job_missing_id", attempts=attempts)
                    await asyncio.sleep(max(0.5, IMAGEN_LIGHT_QUEUE_POLL_SECONDS))
                    continue

                _queue_job_update(job_id=job_id, status="submitted", cuda_job_id=str(cuda_job_id), last_error=None, attempts=attempts)
            except Exception as exc:
                try:
                    print(f"[imagen-light] queue worker error: {exc}", flush=True)
                    print(traceback.format_exc(), flush=True)
                except Exception:
                    pass
                await asyncio.sleep(max(0.5, IMAGEN_LIGHT_QUEUE_POLL_SECONDS))



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


class ImagenGenerateArgs(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = Field(default=None, alias="negativePrompt")
    width: Optional[int] = None
    height: Optional[int] = None
    num_inference_steps: Optional[int] = Field(default=None, alias="numInferenceSteps")
    guidance_scale: Optional[float] = Field(default=None, alias="guidanceScale")
    seed: Optional[int] = None
    approved: Optional[bool] = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> JsonRpcResponse:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data))


def _save_image_from_base64(b64: str, filename: str) -> str:
    img_bytes = base64.b64decode(b64, validate=True)
    path = os.path.join(IMAGES_DIR, filename)
    with open(path, "wb") as f:
        f.write(img_bytes)
    return path


def _public_image_url(filename: str) -> str:
    return f"{PUBLIC_BASE_URL}/images/{filename}"


def _try_cached_preview_response(job_id: str) -> Optional[Dict[str, Any]]:
    filename = f"preview_{job_id}.png"
    path = os.path.join(IMAGES_DIR, filename)
    try:
        if os.path.isfile(path) and os.path.getsize(path) >= max(1, IMAGEN_LIGHT_MIN_PREVIEW_PNG_BYTES):
            return {
                "job_id": job_id,
                "available": True,
                "status": "cached",
                "progress": None,
                "url": _public_image_url(filename),
                "image_url": _public_image_url(filename),
            }
    except Exception:
        return None
    return None


def _cleanup_old_images() -> None:
    cutoff = time.time() - CLEANUP_HOURS * 3600
    for fname in os.listdir(IMAGES_DIR):
        path = os.path.join(IMAGES_DIR, fname)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            try:
                os.remove(path)
            except Exception:
                pass


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "imagen_generate",
            "description": "Generate an image using SDXL via mcp-cuda and return a public image URL.",
            "inputSchema": ImagenGenerateArgs.model_json_schema(),
        }
    ]


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    if IMAGEN_LIGHT_QUEUE_ENABLE:
        print("[imagen-light] queue enabled; starting worker", flush=True)
        _get_queue_conn()
        asyncio.create_task(_queue_worker_loop())


@app.get("/health")
async def health() -> Dict[str, Any]:
    cuda_ok = False
    cuda_status_code: Optional[int] = None
    cuda_error: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            r = await client.get(f"{MCP_CUDA_URL}/health")
            cuda_status_code = int(r.status_code)
            cuda_ok = r.status_code == 200
            if not cuda_ok:
                cuda_error = (r.text or "").strip()[:500] or f"http_{r.status_code}"
    except Exception as exc:
        cuda_ok = False
        cuda_error = str(exc)[:500]

    queue_ok = True
    queue_error: Optional[str] = None
    queue_jobs: Optional[int] = None
    if IMAGEN_LIGHT_QUEUE_ENABLE:
        try:
            conn = _get_queue_conn()
            cur = conn.execute("SELECT COUNT(*) FROM imagen_jobs")
            queue_jobs = int((cur.fetchone() or [0])[0] or 0)
        except Exception as exc:
            queue_ok = False
            queue_error = str(exc)[:500]
    return {
        "status": "ok" if (cuda_ok and queue_ok) else "degraded",
        "service": APP_NAME,
        "version": APP_VERSION,
        "mcp_cuda": cuda_ok,
        "cuda_status_code": cuda_status_code,
        "cuda_error": cuda_error,
        "queue_enabled": bool(IMAGEN_LIGHT_QUEUE_ENABLE),
        "queue_ok": queue_ok,
        "queue_error": queue_error,
        "queue_jobs": queue_jobs,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/.well-known/mcp.json")
async def well_known_manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Thin Imagen/SDXL adapter that proxies mcp-cuda and returns image URLs.",
        "capabilities": {
            "tools": tool_definitions(),
        },
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": tool_definitions()}


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args = (payload or {}).get("arguments") or {}
    if tool == "imagen_generate":
        parsed = ImagenGenerateArgs(**args)
        if IMAGEN_LIGHT_QUEUE_ENABLE:
            job_id = _queue_job_create(parsed.model_dump(exclude_none=True))
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{MCP_CUDA_URL}/imagen/jobs", json=parsed.model_dump(exclude_none=True))
                if r.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"cuda_job_create_failed: {r.text}")
                job_meta = r.json()
            job_id = job_meta.get("jobId")
            if not job_id:
                raise HTTPException(status_code=502, detail="cuda_job_missing_id")
        return {
            "tool": tool,
            "result": {
                "job_id": job_id,
                "status_url": f"{PUBLIC_BASE_URL}/imagen/jobs/{job_id}",
                "preview_url": f"{PUBLIC_BASE_URL}/imagen/jobs/{job_id}/preview",
                "result_url": f"{PUBLIC_BASE_URL}/imagen/jobs/{job_id}/result",
            },
        }
    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


@app.post("/imagen/jobs")
async def imagen_jobs_create(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    parsed = ImagenGenerateArgs(**(payload or {}))
    if IMAGEN_LIGHT_QUEUE_ENABLE:
        job_id = _queue_job_create(parsed.model_dump(exclude_none=True))
        return {"jobId": job_id, "status": "queued"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(IMAGEN_LIGHT_CUDA_TIMEOUT_SECONDS)) as client:
        r = await client.post(f"{MCP_CUDA_URL}/imagen/jobs", json=parsed.model_dump(exclude_none=True))
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"cuda_job_create_failed: {r.text}")
        return r.json()


@app.get("/imagen/jobs/{job_id}")
async def imagen_jobs_status(job_id: str) -> Dict[str, Any]:
    if IMAGEN_LIGHT_QUEUE_ENABLE:
        q = _queue_job_get(job_id)
        if isinstance(q, dict):
            cuda_job_id = str(q.get("cuda_job_id") or "").strip()
            st = str(q.get("status") or "queued")
            if st == "failed":
                return {
                    "jobId": job_id,
                    "status": "failed",
                    "progress": None,
                    "error": str(q.get("last_error") or "").strip() or "job_failed",
                    "cudaJobId": cuda_job_id or None,
                }
            if cuda_job_id:
                async with httpx.AsyncClient(timeout=httpx.Timeout(IMAGEN_LIGHT_CUDA_TIMEOUT_SECONDS)) as client:
                    r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{cuda_job_id}")
                if r.status_code == 404:
                    # CUDA jobs are stored in-memory; if mcp-cuda restarted, the jobId can disappear.
                    # Re-queue the job so the worker can resubmit it.
                    prev_attempts = int(q.get("attempts") or 0)
                    _queue_job_update(
                        job_id=job_id,
                        status="queued",
                        cuda_job_id=None,
                        last_error="cuda_job_not_found_requeued",
                        attempts=prev_attempts,
                    )
                    return {
                        "jobId": job_id,
                        "status": "queued",
                        "progress": None,
                        "error": "cuda_job_not_found_requeued",
                        "cudaJobId": None,
                    }
                if r.status_code >= 400:
                    return {
                        "jobId": job_id,
                        "status": st,
                        "progress": None,
                        "error": str(q.get("last_error") or "").strip() or None,
                        "cudaJobId": cuda_job_id,
                    }
                data = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
                if isinstance(data, dict):
                    data["queueJobId"] = job_id
                    data["queueStatus"] = st
                    return data
            return {
                "jobId": job_id,
                "status": st,
                "progress": None,
                "error": str(q.get("last_error") or "").strip() or None,
                "cudaJobId": None,
            }
    async with httpx.AsyncClient(timeout=httpx.Timeout(IMAGEN_LIGHT_CUDA_TIMEOUT_SECONDS)) as client:
        r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{job_id}")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"cuda_status_failed: {r.text}")
    data = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="cuda_status_invalid")
    return data


@app.get("/imagen/jobs/{job_id}/preview")
async def imagen_jobs_preview(job_id: str) -> Dict[str, Any]:
    queue_job_id = None
    cache_job_id = job_id
    queue_row: Optional[Dict[str, Any]] = None
    if IMAGEN_LIGHT_QUEUE_ENABLE:
        q = _queue_job_get(job_id)
        if isinstance(q, dict):
            queue_row = q
            queue_job_id = job_id
            cache_job_id = job_id
            cuda_job_id = str(q.get("cuda_job_id") or "").strip()
            if not cuda_job_id:
                cached = _try_cached_preview_response(cache_job_id)
                if isinstance(cached, dict):
                    cached["status"] = str(q.get("status") or "queued")
                    return cached
                return {"job_id": job_id, "available": False, "status": str(q.get("status") or "queued"), "progress": None}
            job_id = cuda_job_id

    cached = _try_cached_preview_response(cache_job_id)
    if isinstance(cached, dict):
        return cached
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(IMAGEN_LIGHT_CUDA_TIMEOUT_SECONDS)) as client:
            r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{job_id}/preview")
    except httpx.TimeoutException:
        cached = _try_cached_preview_response(cache_job_id)
        if isinstance(cached, dict):
            return cached
        return {
            "job_id": queue_job_id or cache_job_id,
            "available": False,
            "status": "timeout",
            "progress": None,
        }
    except httpx.RequestError:
        cached = _try_cached_preview_response(cache_job_id)
        if isinstance(cached, dict):
            return cached
        return {
            "job_id": queue_job_id or cache_job_id,
            "available": False,
            "status": "unreachable",
            "progress": None,
        }
    if r.status_code == 404:
        # CUDA jobs are in-memory; if CUDA restarted, the stored cuda_job_id may be stale.
        # Re-queue by clearing cuda_job_id so the worker can resubmit.
        if IMAGEN_LIGHT_QUEUE_ENABLE and queue_job_id and isinstance(queue_row, dict):
            prev_attempts = int(queue_row.get("attempts") or 0)
            _queue_job_update(
                job_id=queue_job_id,
                status="queued",
                cuda_job_id=None,
                last_error="cuda_job_not_found_requeued",
                attempts=prev_attempts,
            )
        cached = _try_cached_preview_response(cache_job_id)
        if isinstance(cached, dict):
            return cached
        return {
            "job_id": queue_job_id or job_id,
            "available": False,
            "status": "not_found",
            "progress": None,
        }
    if r.status_code == 409:
        cached = _try_cached_preview_response(cache_job_id)
        if isinstance(cached, dict):
            return cached
        return {
            "job_id": queue_job_id or job_id,
            "available": False,
            "status": "not_ready",
            "progress": None,
        }
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"cuda_preview_failed: {r.text}")
    data = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="cuda_preview_invalid")

    available = bool(data.get("available"))
    if not available:
        return {
            "job_id": job_id,
            "available": False,
            "status": data.get("status"),
            "progress": data.get("progress"),
        }

    b64 = data.get("imageBase64")
    if not isinstance(b64, str) or not b64:
        return {
            "job_id": job_id,
            "available": False,
            "status": data.get("status"),
            "progress": data.get("progress"),
        }

    filename = f"preview_{cache_job_id}.png"
    path = _save_image_from_base64(b64, filename)
    try:
        if os.path.getsize(path) < max(1, IMAGEN_LIGHT_MIN_PREVIEW_PNG_BYTES):
            return {
                "job_id": job_id,
                "available": False,
                "status": data.get("status"),
                "progress": data.get("progress"),
            }
    except Exception:
        pass
    return {
        "job_id": job_id,
        "available": True,
        "status": data.get("status"),
        "progress": data.get("progress"),
        "url": _public_image_url(filename),
        "image_url": _public_image_url(filename),
    }


@app.get("/imagen/jobs/{job_id}/result")
async def imagen_jobs_result(job_id: str) -> Dict[str, Any]:
    queue_job_id = None
    queue_row: Optional[Dict[str, Any]] = None
    if IMAGEN_LIGHT_QUEUE_ENABLE:
        q = _queue_job_get(job_id)
        if isinstance(q, dict):
            queue_row = q
            queue_job_id = job_id
            cuda_job_id = str(q.get("cuda_job_id") or "").strip()
            if not cuda_job_id:
                raise HTTPException(status_code=409, detail=f"job_not_submitted: {str(q.get('status') or 'queued')}")
            job_id = cuda_job_id
    async with httpx.AsyncClient(timeout=httpx.Timeout(IMAGEN_LIGHT_CUDA_TIMEOUT_SECONDS)) as client:
        status_r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{job_id}")
        if status_r.status_code >= 400:
            if status_r.status_code == 404:
                if IMAGEN_LIGHT_QUEUE_ENABLE and queue_job_id and isinstance(queue_row, dict):
                    prev_attempts = int(queue_row.get("attempts") or 0)
                    _queue_job_update(
                        job_id=queue_job_id,
                        status="queued",
                        cuda_job_id=None,
                        last_error="cuda_job_not_found_requeued",
                        attempts=prev_attempts,
                    )
                raise HTTPException(status_code=409, detail="job_not_found")
            raise HTTPException(status_code=502, detail=f"cuda_status_failed: {status_r.text}")
        status = status_r.json() if status_r.headers.get("content-type", "").lower().startswith("application/json") else {}
        if isinstance(status, dict) and status.get("status") != "succeeded":
            raise HTTPException(status_code=409, detail=f"job_not_succeeded: {status.get('status')}")

        r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{job_id}/result")
    if r.status_code == 404:
        if IMAGEN_LIGHT_QUEUE_ENABLE and queue_job_id and isinstance(queue_row, dict):
            prev_attempts = int(queue_row.get("attempts") or 0)
            _queue_job_update(
                job_id=queue_job_id,
                status="queued",
                cuda_job_id=None,
                last_error="cuda_job_not_found_requeued",
                attempts=prev_attempts,
            )
        raise HTTPException(status_code=409, detail="job_not_found")
    if r.status_code == 409:
        raise HTTPException(status_code=409, detail="job_not_succeeded")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"cuda_result_failed: {r.text}")
    data = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="cuda_result_invalid")
    b64 = data.get("imageBase64")
    if not isinstance(b64, str) or not b64:
        raise HTTPException(status_code=502, detail="cuda_result_missing_image")
    filename = f"{queue_job_id or job_id}.png"
    path = _save_image_from_base64(b64, filename)
    try:
        if os.path.getsize(path) < max(1, IMAGEN_LIGHT_MIN_PNG_BYTES):
            if queue_job_id:
                _queue_job_update(job_id=queue_job_id, status="failed", last_error="cuda_result_suspicious_image")
            raise HTTPException(status_code=502, detail="cuda_result_suspicious_image")
    except HTTPException:
        raise
    except Exception:
        pass
    return {
        "job_id": queue_job_id or job_id,
        "available": True,
        "url": _public_image_url(filename),
        "image_url": _public_image_url(filename),
        "seed": data.get("seed"),
        "width": data.get("width"),
        "height": data.get("height"),
        "steps": data.get("steps"),
        "mime_type": data.get("mimeType"),
    }


@app.get("/imagen/jobs/{job_id}/events")
async def imagen_jobs_events(job_id: str, after: int = 0):
    async def _iter():
        last_seq = int(after or 0)
        yield f"event: hello\ndata: {json.dumps({'jobId': job_id, 'after': last_seq})}\n\n"
        queue_job_id = None
        queue_row: Optional[Dict[str, Any]] = None
        cuda_job_id = job_id
        if IMAGEN_LIGHT_QUEUE_ENABLE:
            q = _queue_job_get(job_id)
            if isinstance(q, dict):
                queue_row = q
                queue_job_id = job_id
                cuda_job_id = str(q.get("cuda_job_id") or "").strip()
                if not cuda_job_id:
                    yield f"event: progress\ndata: {json.dumps({'seq': last_seq, 'type': 'progress', 'progress': None, 'queueStatus': str(q.get('status') or 'queued')})}\n\n"
                    return
        while True:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{cuda_job_id}/events?after={last_seq}")
                    if r.status_code == 200:
                        async for line in r.aiter_lines():
                            if line.startswith("data: "):
                                try:
                                    payload = json.loads(line[6:])
                                    seq = int(payload.get("seq") or last_seq)
                                    if seq > last_seq:
                                        last_seq = seq
                                    yield line + "\n"
                                except Exception:
                                    pass
                            elif line.startswith("event: "):
                                yield line + "\n"
                    elif r.status_code == 404:
                        if IMAGEN_LIGHT_QUEUE_ENABLE and queue_job_id and isinstance(queue_row, dict):
                            prev_attempts = int(queue_row.get("attempts") or 0)
                            _queue_job_update(
                                job_id=queue_job_id,
                                status="queued",
                                cuda_job_id=None,
                                last_error="cuda_job_not_found_requeued",
                                attempts=prev_attempts,
                            )
                        yield "event: error\ndata: {\"message\":\"job_not_found\"}\n\n"
                        return
                    else:
                        yield "event: error\ndata: {\"message\":\"cuda_unreachable\"}\n\n"
                        return
                    # If job ended, break
                    if line.startswith("event: done") or line.startswith("event: error"):
                        return
                await asyncio.sleep(1)
            except Exception:
                yield "event: ping\ndata: {}\n\n"
    return StreamingResponse(_iter(), media_type="text/event-stream")


@app.get("/images/{filename}")
async def serve_image(filename: str):
    path = os.path.join(IMAGES_DIR, filename)
    if not os.path.isfile(path) or not filename.lower().endswith(".png"):
        raise HTTPException(status_code=404, detail="image_not_found")
    from fastapi.responses import FileResponse
    return FileResponse(path, media_type="image/png")


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
        return JsonRpcResponse(
            id=request.id,
            result={"tools": tool_definitions()},
        ).model_dump(exclude_none=True)
    if method in ("tools/call", "call_tool"):
        tool_name = (params.get("name") or params.get("tool") or "").strip()
        arguments_raw = params.get("arguments") or {}
        if not tool_name:
            return _jsonrpc_error(request.id, -32602, "Missing tool name").model_dump(exclude_none=True)
        if tool_name == "imagen_generate":
            try:
                parsed = ImagenGenerateArgs(**(arguments_raw or {}))
                # Queue-first behavior: always return quickly with a local job_id.
                if IMAGEN_LIGHT_QUEUE_ENABLE:
                    job_id = _queue_job_create(parsed.model_dump(exclude_none=True))
                    out: Dict[str, Any] = {
                        "job_id": job_id,
                        "status_url": f"{PUBLIC_BASE_URL}/imagen/jobs/{job_id}",
                        "preview_url": f"{PUBLIC_BASE_URL}/imagen/jobs/{job_id}/preview",
                        "result_url": f"{PUBLIC_BASE_URL}/imagen/jobs/{job_id}/result",
                    }
                else:
                    last_error: str = ""
                    attempt = 0
                    max_attempts = max(1, IMAGEN_LIGHT_NO_CAPACITY_RETRIES)
                    out: Optional[Dict[str, Any]] = None
                    timeout = httpx.Timeout(IMAGEN_LIGHT_CUDA_TIMEOUT_SECONDS)
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        while attempt < max_attempts:
                            attempt += 1
                            r = await client.post(f"{MCP_CUDA_URL}/imagen/jobs", json=parsed.model_dump(exclude_none=True))
                            if r.status_code >= 400:
                                last_error = f"cuda_job_create_failed: {r.text}"
                                if "no_capacity" in (r.text or "") and attempt < max_attempts:
                                    await asyncio.sleep(IMAGEN_LIGHT_NO_CAPACITY_BACKOFF_SECONDS)
                                    continue
                                return _jsonrpc_error(request.id, -32001, last_error).model_dump(exclude_none=True)
                            job_meta = r.json()
                            job_id = job_meta.get("jobId")
                            if not job_id:
                                return _jsonrpc_error(request.id, -32001, "cuda_job_missing_id").model_dump(exclude_none=True)
                            out = {
                                "job_id": job_id,
                                "status_url": f"{PUBLIC_BASE_URL}/imagen/jobs/{job_id}",
                                "preview_url": f"{PUBLIC_BASE_URL}/imagen/jobs/{job_id}/preview",
                                "result_url": f"{PUBLIC_BASE_URL}/imagen/jobs/{job_id}/result",
                            }
                            break

                    if not isinstance(out, dict):
                        msg = last_error or "job_create_failed"
                        return _jsonrpc_error(request.id, -32001, msg).model_dump(exclude_none=True)
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={
                    **out,
                },
            ).model_dump(exclude_none=True)
        return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'").model_dump(exclude_none=True)
    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'").model_dump(exclude_none=True)


if __name__ == "__main__":
    import uvicorn
    import asyncio
    _cleanup_old_images()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
