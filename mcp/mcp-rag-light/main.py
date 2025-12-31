from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_NAME = "mcp-rag-light"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8069"))
MCP_CUDA_URL = (os.getenv("MCP_CUDA_URL") or "http://mcp-cuda:8057").strip().rstrip("/")
PUBLIC_BASE_URL = (os.getenv("RAG_LIGHT_PUBLIC_BASE_URL") or f"http://pc1.vpn:{PORT}").strip().rstrip("/")
HTTP_TIMEOUT = float(os.getenv("RAG_LIGHT_TIMEOUT_SECONDS", "60"))


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


class TextEmbedArgs(BaseModel):
    texts: List[str]
    model: Optional[str] = Field(default=None, description="Embedding model name")


class ImageEmbedArgs(BaseModel):
    images_base64: List[str]
    model: Optional[str] = Field(default=None, description="CLIP model name")


class SearchTextArgs(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)
    model: Optional[str] = Field(default=None, description="Embedding model name")


class SearchImageArgs(BaseModel):
    image_base64: str
    limit: int = Field(default=5, ge=1, le=50)
    model: Optional[str] = Field(default=None, description="CLIP model name")


class RerankTextArgs(BaseModel):
    query: str
    documents: List[str]
    limit: int = Field(default=10, ge=1, le=50)
    model: Optional[str] = Field(default=None, description="Reranking model name")


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> JsonRpcResponse:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data))


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "text_embed",
            "description": "Generate text embeddings using GPU via mcp-cuda",
            "inputSchema": TextEmbedArgs.model_json_schema(),
        },
        {
            "name": "image_embed", 
            "description": "Generate image embeddings using CLIP via mcp-cuda",
            "inputSchema": ImageEmbedArgs.model_json_schema(),
        },
        {
            "name": "search_text",
            "description": "Semantic text search using embeddings via mcp-cuda",
            "inputSchema": SearchTextArgs.model_json_schema(),
        },
        {
            "name": "search_image",
            "description": "Search images by similarity using CLIP embeddings via mcp-cuda", 
            "inputSchema": SearchImageArgs.model_json_schema(),
        },
        {
            "name": "rerank_text",
            "description": "Rerank documents for a query using GPU via mcp-cuda",
            "inputSchema": RerankTextArgs.model_json_schema(),
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
        "description": "Thin RAG adapter that proxies mcp-cuda for embeddings and search",
        "capabilities": {
            "tools": tool_definitions(),
        },
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": tool_definitions()}


async def _cuda_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Make a call to mcp-cuda service"""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(f"{MCP_CUDA_URL}/invoke", json={
            "tool": tool_name,
            "arguments": arguments
        })
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"cuda_call_failed: {r.text}")
        data = r.json()
    
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="cuda_invalid_response")
    return result


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args = (payload or {}).get("arguments") or {}
    
    if tool == "text_embed":
        parsed = TextEmbedArgs(**args)
        result = await _cuda_call("text_embed", parsed.model_dump(exclude_none=True))
        return {"tool": tool, "result": result}
    
    elif tool == "image_embed":
        parsed = ImageEmbedArgs(**args)
        result = await _cuda_call("clip_image_embed", parsed.model_dump(exclude_none=True))
        return {"tool": tool, "result": result}
    
    elif tool == "search_text":
        parsed = SearchTextArgs(**args)
        result = await _cuda_call("search_text", parsed.model_dump(exclude_none=True))
        return {"tool": tool, "result": result}
    
    elif tool == "search_image":
        parsed = SearchImageArgs(**args)
        result = await _cuda_call("search_image", parsed.model_dump(exclude_none=True))
        return {"tool": tool, "result": result}
    
    elif tool == "rerank_text":
        parsed = RerankTextArgs(**args)
        result = await _cuda_call("rerank", parsed.model_dump(exclude_none=True))
        return {"tool": tool, "result": result}
    
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
        
        try:
            if tool_name == "text_embed":
                parsed = TextEmbedArgs(**(arguments_raw or {}))
                result = await _cuda_call("text_embed", parsed.model_dump(exclude_none=True))
            elif tool_name == "image_embed":
                parsed = ImageEmbedArgs(**(arguments_raw or {}))
                result = await _cuda_call("clip_image_embed", parsed.model_dump(exclude_none=True))
            elif tool_name == "search_text":
                parsed = SearchTextArgs(**(arguments_raw or {}))
                result = await _cuda_call("search_text", parsed.model_dump(exclude_none=True))
            elif tool_name == "search_image":
                parsed = SearchImageArgs(**(arguments_raw or {}))
                result = await _cuda_call("search_image", parsed.model_dump(exclude_none=True))
            elif tool_name == "rerank_text":
                parsed = RerankTextArgs(**(arguments_raw or {}))
                result = await _cuda_call("rerank", parsed.model_dump(exclude_none=True))
            else:
                return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'").model_dump(exclude_none=True)
            
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(result)}]},
            ).model_dump(exclude_none=True)
            
        except HTTPException as exc:
            return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
        except Exception as exc:
            return _jsonrpc_error(request.id, -32001, f"Unexpected error: {exc}").model_dump(exclude_none=True)
    
    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'").model_dump(exclude_none=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
