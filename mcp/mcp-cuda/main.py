from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_NAME = "mcp-cuda"
APP_VERSION = "0.1.0"


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

        return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'").model_dump(exclude_none=True)

    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'").model_dump(exclude_none=True)
