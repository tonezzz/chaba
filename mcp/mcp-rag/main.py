from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
import numpy as np
from fastapi import Body, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, validator
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer
from PIL import Image
import io

APP_NAME = "mcp-rag"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8055"))

QDRANT_URL = (os.getenv("QDRANT_URL") or "http://qdrant:6333").strip()
QDRANT_TEXT_COLLECTION = (os.getenv("QDRANT_TEXT_COLLECTION") or "rag_text").strip()
QDRANT_IMAGE_COLLECTION = (os.getenv("QDRANT_IMAGE_COLLECTION") or "rag_image").strip()

OLLAMA_URL = (os.getenv("OLLAMA_URL") or "http://ollama:11434").strip().rstrip("/")
OLLAMA_EMBED_MODEL = (os.getenv("OLLAMA_EMBED_MODEL") or "nomic-embed-text").strip()

CLIP_MODEL = (os.getenv("CLIP_MODEL") or "clip-ViT-B-32").strip()

HTTP_TIMEOUT = float(os.getenv("MCP_RAG_TIMEOUT_SECONDS", "60"))

MCP_RAG_TOKEN = (os.getenv("MCP_RAG_TOKEN") or "").strip()
MCP_RAG_ACL_RAW = (os.getenv("MCP_RAG_ACL") or "").strip()


def _parse_acl() -> Dict[str, Any]:
    if not MCP_RAG_ACL_RAW:
        return {}
    try:
        out = json.loads(MCP_RAG_ACL_RAW)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Invalid MCP_RAG_ACL JSON: {exc}")
    if not isinstance(out, dict):
        raise RuntimeError("Invalid MCP_RAG_ACL JSON: expected object")
    return out


_ACL = _parse_acl()


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    if not authorization.lower().startswith("bearer "):
        return ""
    return authorization.split(" ", 1)[1].strip()


def _token_rules(token: str) -> Dict[str, Any]:
    tokens = _ACL.get("tokens") if isinstance(_ACL, dict) else None
    if isinstance(tokens, dict) and token in tokens and isinstance(tokens[token], dict):
        return tokens[token]
    default = _ACL.get("default") if isinstance(_ACL, dict) else None
    if isinstance(default, dict):
        return default
    return {}


def _is_allowed(values: Any, wanted: str) -> bool:
    if values is None:
        return False
    if values == "*":
        return True
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return False
    return ("*" in values) or (wanted in values)


def _require_access(
    *,
    authorization: Optional[str],
    action: str,
    datastore: str,
    group: str,
) -> None:
    if not MCP_RAG_TOKEN and not MCP_RAG_ACL_RAW:
        return

    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing_or_invalid_token")

    if MCP_RAG_TOKEN and token != MCP_RAG_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")

    if MCP_RAG_ACL_RAW:
        rules = _token_rules(token)
        actions = rules.get("actions")
        groups = rules.get("groups")
        datastores = rules.get("datastores")
        if actions is not None and not _is_allowed(actions, action):
            raise HTTPException(status_code=403, detail="forbidden")
        if groups is not None and not _is_allowed(groups, group):
            raise HTTPException(status_code=403, detail="forbidden")
        if datastores is not None and not _is_allowed(datastores, datastore):
            raise HTTPException(status_code=403, detail="forbidden")


def _utc_ms() -> int:
    return int(time.time() * 1000)


def _to_qdrant_point_id(value: Optional[str], *, prefix: str, fallback_seed: str) -> str:
    """Qdrant point IDs must be an unsigned int or a UUID.

    We accept user-friendly string IDs and convert them into a stable UUID.
    """

    raw = (value or "").strip()
    if raw:
        try:
            return str(uuid.UUID(raw))
        except Exception:
            # Stable mapping for arbitrary string ids
            return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:{raw}"))

    # Generate a new UUID if caller didn't provide an id.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:auto:{fallback_seed}"))


def _ensure_nonempty(value: str, name: str) -> str:
    v = (value or "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _qdrant_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL)


_clip_model: Optional[SentenceTransformer] = None


def _get_clip_model() -> SentenceTransformer:
    global _clip_model
    if _clip_model is None:
        _clip_model = SentenceTransformer(CLIP_MODEL)
    return _clip_model


async def _ollama_embed_text(texts: List[str]) -> List[List[float]]:
    base = _ensure_nonempty(OLLAMA_URL, "OLLAMA_URL")
    model = _ensure_nonempty(OLLAMA_EMBED_MODEL, "OLLAMA_EMBED_MODEL")

    # Ollama embeddings API returns a single vector per request.
    url = f"{base}/api/embeddings"

    out: List[List[float]] = []
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for t in texts:
            prompt = (t or "").strip()
            if not prompt:
                out.append([])
                continue
            r = await client.post(url, json={"model": model, "prompt": prompt})
            if r.status_code >= 400:
                raise HTTPException(status_code=502, detail=r.text or f"ollama_http_{r.status_code}")
            data = r.json()
            emb = data.get("embedding")
            if not isinstance(emb, list):
                raise HTTPException(status_code=502, detail="ollama_invalid_embedding")
            out.append([float(x) for x in emb])
    return out


def _decode_base64_to_bytes(data_b64: str) -> bytes:
    try:
        return base64.b64decode(data_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_base64: {exc}")


def _embed_image_bytes(image_bytes: bytes) -> List[float]:
    model = _get_clip_model()
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_image: {exc}")

    # Transformers' CLIP image preprocessor can mis-detect channel dimension for
    # tiny images (e.g. 1x1). Resizing avoids ambiguous (1, 1, 3) shapes.
    if img.width < 8 or img.height < 8:
        img = img.resize((224, 224))

    vec = model.encode(img, normalize_embeddings=True)
    return [float(x) for x in np.asarray(vec).tolist()]


def _ensure_collection(client: QdrantClient, name: str, vector_size: int) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if name in existing:
        info = client.get_collection(name)
        params = info.config.params
        if not params or not params.vectors:
            return
        current_size = params.vectors.size  # type: ignore[attr-defined]
        if int(current_size) != int(vector_size):
            raise RuntimeError(f"Qdrant collection '{name}' vector size mismatch: {current_size} != {vector_size}")
        return

    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=int(vector_size), distance=Distance.COSINE),
    )


class UpsertTextItem(BaseModel):
    id: Optional[str] = None
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @validator("text")
    def validate_text(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("text cannot be empty")
        return v


class UpsertTextArgs(BaseModel):
    group: str = "default"
    items: List[UpsertTextItem]


class UpsertImageItem(BaseModel):
    id: Optional[str] = None
    image_base64: str = Field(..., alias="imageBase64")
    mime_type: Optional[str] = Field(default=None, alias="mimeType")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @validator("image_base64")
    def validate_b64(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("imageBase64 cannot be empty")
        return v


class UpsertImageArgs(BaseModel):
    group: str = "default"
    items: List[UpsertImageItem]


class SearchTextArgs(BaseModel):
    group: str = "default"
    query: str
    limit: int = 5

    @validator("query")
    def validate_query(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("query cannot be empty")
        return v


class SearchImageArgs(BaseModel):
    group: str = "default"
    image_base64: str = Field(..., alias="imageBase64")
    limit: int = 5


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcRequest(BaseModel):
    jsonrpc: Optional[str] = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Any
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


app = FastAPI(title=APP_NAME, version=APP_VERSION)


def _tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "upsert_text",
            "description": "Upsert text items into Qdrant using Ollama embeddings.",
            "inputSchema": UpsertTextArgs.model_json_schema(),
        },
        {
            "name": "search_text",
            "description": "Semantic search over text collection.",
            "inputSchema": SearchTextArgs.model_json_schema(),
        },
        {
            "name": "upsert_image",
            "description": "Upsert images into Qdrant using a CLIP embedding model.",
            "inputSchema": UpsertImageArgs.model_json_schema(),
        },
        {
            "name": "search_image",
            "description": "Search images by similarity using a CLIP embedding model.",
            "inputSchema": SearchImageArgs.model_json_schema(),
        },
    ]


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "qdrantUrl": QDRANT_URL,
        "collections": {
            "text": QDRANT_TEXT_COLLECTION,
            "image": QDRANT_IMAGE_COLLECTION,
        },
        "ollamaUrl": OLLAMA_URL,
        "ollamaEmbedModel": OLLAMA_EMBED_MODEL,
        "clipModel": CLIP_MODEL,
        "timestampMs": _utc_ms(),
    }


@app.get("/tools")
def tools() -> Dict[str, Any]:
    return {"tools": _tool_definitions()}


@app.get("/.well-known/mcp.json")
def well_known() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "RAG provider: text + image retrieval via Qdrant (text embeddings from Ollama; image embeddings via CLIP).",
        "capabilities": {"tools": _tool_definitions()},
    }


async def _handle_upsert_text(args: UpsertTextArgs, *, authorization: Optional[str]) -> Dict[str, Any]:
    if not args.items:
        raise HTTPException(status_code=400, detail="items cannot be empty")

    group_default = (args.group or "default").strip() or "default"
    _require_access(authorization=authorization, action="upsert", datastore="qdrant:text", group=group_default)

    texts = [it.text for it in args.items]
    vectors = await _ollama_embed_text(texts)
    if not vectors or not vectors[0]:
        raise HTTPException(status_code=502, detail="ollama_returned_empty_embedding")

    vec_size = len(vectors[0])
    client = _qdrant_client()
    _ensure_collection(client, QDRANT_TEXT_COLLECTION, vec_size)

    points: List[PointStruct] = []
    for it, vec in zip(args.items, vectors, strict=False):
        point_id = _to_qdrant_point_id(it.id, prefix="txt", fallback_seed=f"{_utc_ms()}:{it.text}")
        meta = it.metadata or {}
        group_value = (str(meta.get("group") or group_default)).strip() or group_default
        _require_access(authorization=authorization, action="upsert", datastore="qdrant:text", group=group_value)
        payload = {"group": group_value, "text": it.text, **meta}
        points.append(PointStruct(id=point_id, vector=vec, payload=payload))

    client.upsert(collection_name=QDRANT_TEXT_COLLECTION, points=points)
    return {"upserted": len(points), "collection": QDRANT_TEXT_COLLECTION}


async def _handle_search_text(args: SearchTextArgs, *, authorization: Optional[str]) -> Dict[str, Any]:
    group_value = (args.group or "default").strip() or "default"
    _require_access(authorization=authorization, action="search", datastore="qdrant:text", group=group_value)

    limit = max(1, min(int(args.limit), 50))
    vecs = await _ollama_embed_text([args.query])
    query_vec = vecs[0]
    if not query_vec:
        raise HTTPException(status_code=502, detail="ollama_returned_empty_embedding")

    client = _qdrant_client()
    hits = client.search(
        collection_name=QDRANT_TEXT_COLLECTION,
        query_vector=query_vec,
        limit=limit,
        query_filter=Filter(must=[FieldCondition(key="group", match=MatchValue(value=group_value))]),
    )
    results = [
        {
            "id": h.id,
            "score": h.score,
            "payload": h.payload,
        }
        for h in hits
    ]
    return {"results": results, "collection": QDRANT_TEXT_COLLECTION}


def _handle_upsert_image(args: UpsertImageArgs, *, authorization: Optional[str]) -> Dict[str, Any]:
    if not args.items:
        raise HTTPException(status_code=400, detail="items cannot be empty")

    group_default = (args.group or "default").strip() or "default"
    _require_access(authorization=authorization, action="upsert", datastore="qdrant:image", group=group_default)

    vectors: List[List[float]] = []
    for it in args.items:
        raw = _decode_base64_to_bytes(it.image_base64)
        vectors.append(_embed_image_bytes(raw))

    vec_size = len(vectors[0])
    client = _qdrant_client()
    _ensure_collection(client, QDRANT_IMAGE_COLLECTION, vec_size)

    points: List[PointStruct] = []
    for it, vec in zip(args.items, vectors, strict=False):
        point_id = _to_qdrant_point_id(it.id, prefix="img", fallback_seed=f"{_utc_ms()}:{it.image_base64[:64]}")
        meta = it.metadata or {}
        group_value = (str(meta.get("group") or group_default)).strip() or group_default
        _require_access(authorization=authorization, action="upsert", datastore="qdrant:image", group=group_value)
        payload = {"group": group_value, "mimeType": it.mime_type, **meta}
        points.append(PointStruct(id=point_id, vector=vec, payload=payload))

    client.upsert(collection_name=QDRANT_IMAGE_COLLECTION, points=points)
    return {"upserted": len(points), "collection": QDRANT_IMAGE_COLLECTION}


def _handle_search_image(args: SearchImageArgs, *, authorization: Optional[str]) -> Dict[str, Any]:
    group_value = (args.group or "default").strip() or "default"
    _require_access(authorization=authorization, action="search", datastore="qdrant:image", group=group_value)

    limit = max(1, min(int(args.limit), 50))
    raw = _decode_base64_to_bytes(args.image_base64)
    query_vec = _embed_image_bytes(raw)

    client = _qdrant_client()
    hits = client.search(
        collection_name=QDRANT_IMAGE_COLLECTION,
        query_vector=query_vec,
        limit=limit,
        query_filter=Filter(must=[FieldCondition(key="group", match=MatchValue(value=group_value))]),
    )
    results = [
        {
            "id": h.id,
            "score": h.score,
            "payload": h.payload,
        }
        for h in hits
    ]
    return {"results": results, "collection": QDRANT_IMAGE_COLLECTION}


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...), authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args_raw = (payload or {}).get("arguments") or (payload or {}).get("args") or {}

    if tool == "upsert_text":
        parsed = UpsertTextArgs(**args_raw)
        return {"tool": tool, "result": await _handle_upsert_text(parsed, authorization=authorization)}

    if tool == "search_text":
        parsed = SearchTextArgs(**args_raw)
        return {"tool": tool, "result": await _handle_search_text(parsed, authorization=authorization)}

    if tool == "upsert_image":
        parsed = UpsertImageArgs(**args_raw)
        return {"tool": tool, "result": _handle_upsert_image(parsed, authorization=authorization)}

    if tool == "search_image":
        parsed = SearchImageArgs(**args_raw)
        return {"tool": tool, "result": _handle_search_image(parsed, authorization=authorization)}

    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data)).model_dump(
        exclude_none=True
    )


@app.post("/mcp")
async def mcp(payload: Dict[str, Any] = Body(...), authorization: Optional[str] = Header(default=None)) -> Any:
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
        return JsonRpcResponse(id=request.id, result={"tools": _tool_definitions()}).model_dump(exclude_none=True)

    if method in ("tools/call", "call_tool"):
        tool_name = (params.get("name") or params.get("tool") or "").strip()
        arguments_raw = params.get("arguments") or {}
        if not tool_name:
            return _jsonrpc_error(request.id, -32602, "Missing tool name")

        if tool_name == "upsert_text":
            parsed = UpsertTextArgs(**(arguments_raw or {}))
            try:
                out = await _handle_upsert_text(parsed, authorization=authorization)
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, exc.detail)
            return JsonRpcResponse(id=request.id, result={"content": [{"type": "text", "text": str(out)}]}).model_dump(
                exclude_none=True
            )

        if tool_name == "search_text":
            parsed = SearchTextArgs(**(arguments_raw or {}))
            try:
                out = await _handle_search_text(parsed, authorization=authorization)
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, exc.detail)
            return JsonRpcResponse(id=request.id, result={"content": [{"type": "text", "text": str(out)}]}).model_dump(
                exclude_none=True
            )

        if tool_name == "upsert_image":
            parsed = UpsertImageArgs(**(arguments_raw or {}))
            try:
                out = _handle_upsert_image(parsed, authorization=authorization)
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, exc.detail)
            return JsonRpcResponse(id=request.id, result={"content": [{"type": "text", "text": str(out)}]}).model_dump(
                exclude_none=True
            )

        if tool_name == "search_image":
            parsed = SearchImageArgs(**(arguments_raw or {}))
            try:
                out = _handle_search_image(parsed, authorization=authorization)
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, exc.detail)
            return JsonRpcResponse(id=request.id, result={"content": [{"type": "text", "text": str(out)}]}).model_dump(
                exclude_none=True
            )

        return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'")

    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'")
