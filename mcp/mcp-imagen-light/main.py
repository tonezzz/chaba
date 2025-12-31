from __future__ import annotations

import base64
import io
import json
import os
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

os.makedirs(IMAGES_DIR, exist_ok=True)


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


@app.get("/health")
async def health() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{MCP_CUDA_URL}/health")
            cuda_ok = r.status_code == 200
    except Exception:
        cuda_ok = False
    return {
        "status": "ok" if cuda_ok else "degraded",
        "service": APP_NAME,
        "version": APP_VERSION,
        "mcp_cuda": cuda_ok,
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
        # Create job via mcp-cuda
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{MCP_CUDA_URL}/imagen/jobs", json=parsed.model_dump(exclude_none=True))
            if r.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"cuda_job_create_failed: {r.text}")
            job_meta = r.json()
        job_id = job_meta.get("jobId")
        if not job_id:
            raise HTTPException(status_code=502, detail="cuda_job_missing_id")
        # Poll until done (simple blocking for tool use)
        while True:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{job_id}")
                if r.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"cuda_status_failed: {r.text}")
                status = r.json()
                if status.get("status") in ("succeeded", "failed"):
                    break
                await asyncio.sleep(1)
        if status.get("status") != "succeeded":
            raise HTTPException(status_code=502, detail=f"job_failed: {status.get('error')}")
        # Fetch result
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{job_id}/result")
            if r.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"cuda_result_failed: {r.text}")
            result = r.json()
        b64 = result.get("imageBase64")
        if not isinstance(b64, str):
            raise HTTPException(status_code=502, detail="cuda_result_missing_image")
        # Save and return URL
        filename = f"{job_id}.png"
        _save_image_from_base64(b64, filename)
        image_url = f"{PUBLIC_BASE_URL}/images/{filename}"
        return {
            "tool": tool,
            "result": {
                "image_url": image_url,
                "job_id": job_id,
                "seed": result.get("seed"),
                "width": result.get("width"),
                "height": result.get("height"),
                "steps": result.get("steps"),
                "mime_type": result.get("mimeType"),
            },
        }
    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


@app.get("/imagen/jobs")
async def imagen_jobs_create(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    parsed = ImagenGenerateArgs(**(payload or {}))
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{MCP_CUDA_URL}/imagen/jobs", json=parsed.model_dump(exclude_none=True))
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"cuda_job_create_failed: {r.text}")
        return r.json()


@app.get("/imagen/jobs/{job_id}/events")
async def imagen_jobs_events(job_id: str, after: int = 0):
    async def _iter():
        last_seq = int(after or 0)
        yield f"event: hello\ndata: {json.dumps({'jobId': job_id, 'after': last_seq})}\n\n"
        while True:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{job_id}/events?after={last_seq}")
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
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(f"{MCP_CUDA_URL}/imagen/jobs", json=parsed.model_dump(exclude_none=True))
                    if r.status_code >= 400:
                        return _jsonrpc_error(request.id, -32001, f"cuda_job_create_failed: {r.text}").model_dump(exclude_none=True)
                    job_meta = r.json()
                job_id = job_meta.get("jobId")
                if not job_id:
                    return _jsonrpc_error(request.id, -32001, "cuda_job_missing_id").model_dump(exclude_none=True)
                while True:
                    async with httpx.AsyncClient(timeout=10) as client:
                        r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{job_id}")
                        if r.status_code >= 400:
                            return _jsonrpc_error(request.id, -32001, f"cuda_status_failed: {r.text}").model_dump(exclude_none=True)
                        status = r.json()
                        if status.get("status") in ("succeeded", "failed"):
                            break
                        await asyncio.sleep(1)
                if status.get("status") != "succeeded":
                    return _jsonrpc_error(request.id, -32001, f"job_failed: {status.get('error')}").model_dump(exclude_none=True)
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(f"{MCP_CUDA_URL}/imagen/jobs/{job_id}/result")
                    if r.status_code >= 400:
                        return _jsonrpc_error(request.id, -32001, f"cuda_result_failed: {r.text}").model_dump(exclude_none=True)
                    result = r.json()
                b64 = result.get("imageBase64")
                if not isinstance(b64, str):
                    return _jsonrpc_error(request.id, -32001, "cuda_result_missing_image").model_dump(exclude_none=True)
                filename = f"{job_id}.png"
                _save_image_from_base64(b64, filename)
                image_url = f"{PUBLIC_BASE_URL}/images/{filename}"
                out = {
                    "image_url": image_url,
                    "job_id": job_id,
                    "seed": result.get("seed"),
                    "width": result.get("width"),
                    "height": result.get("height"),
                    "steps": result.get("steps"),
                    "mime_type": result.get("mimeType"),
                }
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)
        return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'").model_dump(exclude_none=True)
    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'").model_dump(exclude_none=True)


if __name__ == "__main__":
    import uvicorn
    import asyncio
    _cleanup_old_images()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
