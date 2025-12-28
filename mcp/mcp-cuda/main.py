from __future__ import annotations

import base64
import io
import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel, Field
from sentence_transformers import CrossEncoder, SentenceTransformer
import torch

APP_NAME = "mcp-cuda"
APP_VERSION = "0.1.0"


CLIP_MODEL = (os.getenv("CLIP_MODEL") or "clip-ViT-B-32").strip()
MAX_IMAGE_ITEMS = int(os.getenv("MCP_CUDA_MAX_IMAGE_ITEMS", "32"))

TEXT_EMBED_MODEL = (os.getenv("TEXT_EMBED_MODEL") or "all-MiniLM-L6-v2").strip()
RERANK_MODEL = (os.getenv("RERANK_MODEL") or "cross-encoder/ms-marco-MiniLM-L-6-v2").strip()
MAX_TEXT_ITEMS = int(os.getenv("MCP_CUDA_MAX_TEXT_ITEMS", "128"))
MAX_RERANK_DOCS = int(os.getenv("MCP_CUDA_MAX_RERANK_DOCS", "64"))


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


class ToolCallArgs(BaseModel):
    pass


class ToolCallPayload(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ClipImageEmbedArgs(BaseModel):
    images_base64: List[str] = Field(..., alias="imagesBase64")
    normalize: bool = True
    model: Optional[str] = None


class TextEmbedArgs(BaseModel):
    texts: List[str]
    normalize: bool = True
    model: Optional[str] = None


class RerankArgs(BaseModel):
    query: str
    documents: List[str]
    model: Optional[str] = None


def _run(cmd: List[str], timeout_seconds: int = 10) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}


def _torch_info() -> Dict[str, Any]:
    cuda_available = bool(torch.cuda.is_available())
    out: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "torch": {
            "version": torch.__version__,
            "cuda_available": cuda_available,
            "cuda_version": getattr(torch.version, "cuda", None),
        },
    }
    if cuda_available:
        out["torch"]["cuda_device_count"] = int(torch.cuda.device_count())
        out["torch"]["cuda_current_device"] = int(torch.cuda.current_device())
        out["torch"]["cuda_device_name"] = torch.cuda.get_device_name(torch.cuda.current_device())
    return out


_clip_model: Optional[SentenceTransformer] = None

_text_model: Optional[SentenceTransformer] = None
_rerank_model: Optional[CrossEncoder] = None


def _get_clip_model(model_name: Optional[str]) -> SentenceTransformer:
    global _clip_model
    selected = (model_name or CLIP_MODEL).strip() or CLIP_MODEL
    if _clip_model is None or getattr(_clip_model, "_chaba_model_name", None) != selected:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        m = SentenceTransformer(selected, device=device)
        setattr(m, "_chaba_model_name", selected)
        _clip_model = m
    return _clip_model


def _get_text_model(model_name: Optional[str]) -> SentenceTransformer:
    global _text_model
    selected = (model_name or TEXT_EMBED_MODEL).strip() or TEXT_EMBED_MODEL
    if _text_model is None or getattr(_text_model, "_chaba_model_name", None) != selected:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        m = SentenceTransformer(selected, device=device)
        setattr(m, "_chaba_model_name", selected)
        _text_model = m
    return _text_model


def _get_rerank_model(model_name: Optional[str]) -> CrossEncoder:
    global _rerank_model
    selected = (model_name or RERANK_MODEL).strip() or RERANK_MODEL
    if _rerank_model is None or getattr(_rerank_model, "_chaba_model_name", None) != selected:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        m = CrossEncoder(selected, device=device)
        setattr(m, "_chaba_model_name", selected)
        _rerank_model = m
    return _rerank_model


def _decode_b64(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_base64: {exc}")


def _clip_image_embed(images_base64: List[str], *, normalize: bool, model_name: Optional[str]) -> Dict[str, Any]:
    items = [str(x or "").strip() for x in (images_base64 or [])]
    if not items:
        raise HTTPException(status_code=400, detail="imagesBase64_required")
    if len(items) > MAX_IMAGE_ITEMS:
        raise HTTPException(status_code=400, detail=f"too_many_images: max={MAX_IMAGE_ITEMS}")

    model = _get_clip_model(model_name)

    images: List[Image.Image] = []
    for b64 in items:
        raw = _decode_b64(b64)
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid_image: {exc}")
        if img.width < 8 or img.height < 8:
            img = img.resize((224, 224))
        images.append(img)

    vecs = model.encode(images, normalize_embeddings=bool(normalize))
    arr = np.asarray(vecs)
    return {
        "model": getattr(model, "_chaba_model_name", CLIP_MODEL),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "count": int(arr.shape[0]) if arr.ndim >= 1 else 0,
        "dim": int(arr.shape[1]) if arr.ndim == 2 else 0,
        "vectors": arr.astype(float).tolist(),
    }


def _text_embed(texts: List[str], *, normalize: bool, model_name: Optional[str]) -> Dict[str, Any]:
    items = [str(t or "") for t in (texts or [])]
    if not items:
        raise HTTPException(status_code=400, detail="texts_required")
    if len(items) > MAX_TEXT_ITEMS:
        raise HTTPException(status_code=400, detail=f"too_many_texts: max={MAX_TEXT_ITEMS}")

    model = _get_text_model(model_name)
    vecs = model.encode(items, normalize_embeddings=bool(normalize))
    arr = np.asarray(vecs)
    return {
        "model": getattr(model, "_chaba_model_name", TEXT_EMBED_MODEL),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "count": int(arr.shape[0]) if arr.ndim >= 1 else 0,
        "dim": int(arr.shape[1]) if arr.ndim == 2 else 0,
        "vectors": arr.astype(float).tolist(),
    }


def _rerank(query: str, documents: List[str], *, model_name: Optional[str]) -> Dict[str, Any]:
    q = (query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query_required")
    docs = [str(d or "") for d in (documents or [])]
    if not docs:
        raise HTTPException(status_code=400, detail="documents_required")
    if len(docs) > MAX_RERANK_DOCS:
        raise HTTPException(status_code=400, detail=f"too_many_documents: max={MAX_RERANK_DOCS}")

    model = _get_rerank_model(model_name)
    pairs = [(q, d) for d in docs]
    scores_raw = model.predict(pairs)
    scores = [float(x) for x in np.asarray(scores_raw).tolist()]
    ranked = sorted(
        [{"index": i, "score": s, "text": docs[i]} for i, s in enumerate(scores)],
        key=lambda x: x["score"],
        reverse=True,
    )
    return {
        "model": getattr(model, "_chaba_model_name", RERANK_MODEL),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "query": q,
        "results": ranked,
    }


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "cuda_info",
            "description": "Return basic GPU/CUDA availability info via nvidia-smi.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "nvidia_smi_query",
            "description": "Run a fixed nvidia-smi query (no arbitrary shell).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "nvidia-smi --query-gpu fields (e.g. name,driver_version,memory.total,memory.used)",
                    }
                },
                "required": ["fields"],
            },
        },
        {
            "name": "torch_info",
            "description": "Return torch/CUDA availability details for debugging.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "clip_image_embed",
            "description": "Compute CLIP image embeddings on GPU (batch). Input is base64-encoded image bytes.",
            "inputSchema": ClipImageEmbedArgs.model_json_schema(),
        },
        {
            "name": "text_embed",
            "description": "Compute text embeddings on GPU (batch) using sentence-transformers.",
            "inputSchema": TextEmbedArgs.model_json_schema(),
        },
        {
            "name": "rerank",
            "description": "Rerank candidate documents for a query using a cross-encoder (GPU if available).",
            "inputSchema": RerankArgs.model_json_schema(),
        },
    ]


def _cuda_info() -> Dict[str, Any]:
    smi = _run(["nvidia-smi", "-L"], timeout_seconds=10)
    query = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout_seconds=10,
    )

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "smi_list": smi,
        "smi_query": query,
        "notes": {
            "requires": "Docker GPU support + NVIDIA container runtime on host",
        },
    }


def _nvidia_smi_query(fields: List[str]) -> Dict[str, Any]:
    cleaned = [str(f).strip() for f in (fields or []) if str(f).strip()]
    if not cleaned:
        raise HTTPException(status_code=400, detail="fields_required")

    cmd = [
        "nvidia-smi",
        f"--query-gpu={','.join(cleaned)}",
        "--format=csv,noheader,nounits",
    ]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": cleaned,
        "result": _run(cmd, timeout_seconds=10),
    }


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> JsonRpcResponse:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data))


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


@app.get("/health")
async def health() -> Dict[str, Any]:
    smi = _run(["nvidia-smi", "-L"], timeout_seconds=5)
    status = "ok" if smi.get("ok") else "degraded"
    return {
        "status": status,
        "service": APP_NAME,
        "version": APP_VERSION,
        "nvidiaSmi": smi.get("ok"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/.well-known/mcp.json")
async def well_known_manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "CUDA/GPU utility MCP provider (centralized GPU access).",
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

    if tool == "cuda_info":
        return {"tool": tool, "result": _cuda_info()}

    if tool == "nvidia_smi_query":
        fields = args.get("fields")
        if not isinstance(fields, list):
            raise HTTPException(status_code=400, detail="fields_must_be_array")
        return {"tool": tool, "result": _nvidia_smi_query(fields)}

    if tool == "torch_info":
        return {"tool": tool, "result": _torch_info()}

    if tool == "clip_image_embed":
        parsed = ClipImageEmbedArgs(**args)
        return {
            "tool": tool,
            "result": _clip_image_embed(
                parsed.images_base64,
                normalize=bool(parsed.normalize),
                model_name=parsed.model,
            ),
        }

    if tool == "text_embed":
        parsed = TextEmbedArgs(**args)
        return {
            "tool": tool,
            "result": _text_embed(parsed.texts, normalize=bool(parsed.normalize), model_name=parsed.model),
        }

    if tool == "rerank":
        parsed = RerankArgs(**args)
        return {
            "tool": tool,
            "result": _rerank(parsed.query, parsed.documents, model_name=parsed.model),
        }

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
        return JsonRpcResponse(
            id=request.id,
            result={"tools": tool_definitions()},
        ).model_dump(exclude_none=True)

    if method in ("tools/call", "call_tool"):
        tool_name = (params.get("name") or params.get("tool") or "").strip()
        arguments_raw = params.get("arguments") or {}
        if not tool_name:
            return _jsonrpc_error(request.id, -32602, "Missing tool name").model_dump(exclude_none=True)

        if tool_name == "cuda_info":
            out = _cuda_info()
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "text_embed":
            try:
                parsed = TextEmbedArgs(**(arguments_raw or {}))
                out = _text_embed(parsed.texts, normalize=bool(parsed.normalize), model_name=parsed.model)
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "rerank":
            try:
                parsed = RerankArgs(**(arguments_raw or {}))
                out = _rerank(parsed.query, parsed.documents, model_name=parsed.model)
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "nvidia_smi_query":
            fields = arguments_raw.get("fields")
            if not isinstance(fields, list):
                return _jsonrpc_error(request.id, -32602, "fields must be an array").model_dump(
                    exclude_none=True
                )
            out = _nvidia_smi_query(fields)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "torch_info":
            out = _torch_info()
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "clip_image_embed":
            try:
                parsed = ClipImageEmbedArgs(**(arguments_raw or {}))
                out = _clip_image_embed(
                    parsed.images_base64,
                    normalize=bool(parsed.normalize),
                    model_name=parsed.model,
                )
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'").model_dump(exclude_none=True)

    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'").model_dump(exclude_none=True)
