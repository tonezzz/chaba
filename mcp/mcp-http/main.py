from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel, Field

APP_NAME = "mcp-http"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8067"))
TIMEOUT_SECONDS = float(os.getenv("MCP_HTTP_TIMEOUT_SECONDS", "30"))
ALLOWED_HOSTS_RAW = (os.getenv("MCP_HTTP_ALLOWED_HOSTS") or "").strip()


def _utc_ms() -> int:
    import time

    return int(time.time() * 1000)


def _parse_allowed_hosts(raw: str) -> List[str]:
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    return parts


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except Exception:
        return False


def _match_host(pattern: str, host: str) -> bool:
    p = pattern.strip().lower()
    h = (host or "").strip().lower()
    if not p or not h:
        return False
    if p == h:
        return True
    if p.startswith("*."):
        suffix = p[1:]
        return h.endswith(suffix) and h != suffix.lstrip(".")
    return False


def _ensure_allowed_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="invalid_scheme")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="missing_host")

    allowed = _parse_allowed_hosts(ALLOWED_HOSTS_RAW)
    if allowed:
        if not any(_match_host(p, host) for p in allowed):
            raise HTTPException(status_code=403, detail=f"host_not_allowed: {host}")
        return

    # Default-safe behavior if allowlist unset: block private IPs and localhost.
    if host in ("localhost", "127.0.0.1"):
        raise HTTPException(status_code=403, detail="host_not_allowed_default")
    if _is_ip_literal(host):
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise HTTPException(status_code=403, detail="host_not_allowed_default")


class HttpRequestArgs(BaseModel):
    method: str = Field("GET")
    url: str
    headers: Dict[str, str] = Field(default_factory=dict)
    params: Dict[str, str] = Field(default_factory=dict)
    json: Optional[Any] = None
    body: Optional[str] = None


class HttpResponse(BaseModel):
    status: int
    headers: Dict[str, str]
    text: str


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
    id: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


def _tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "http_get",
            "description": "HTTP GET (allowlisted hostnames). Returns status, headers, and response text.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                    "params": {"type": "object", "additionalProperties": {"type": "string"}},
                },
                "required": ["url"],
            },
        },
        {
            "name": "http_post_json",
            "description": "HTTP POST with JSON body (allowlisted hostnames).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                    "params": {"type": "object", "additionalProperties": {"type": "string"}},
                    "json": {},
                },
                "required": ["url", "json"],
            },
        },
        {
            "name": "http_request",
            "description": "Generic HTTP request (allowlisted hostnames). Supports method + headers + params + json/body.",
            "inputSchema": HttpRequestArgs.model_json_schema(),
        },
    ]


async def _do_request(args: HttpRequestArgs) -> HttpResponse:
    _ensure_allowed_url(args.url)

    method = (args.method or "GET").upper().strip()
    if not re.match(r"^[A-Z]+$", method):
        raise HTTPException(status_code=400, detail="invalid_method")

    headers = {str(k): str(v) for k, v in (args.headers or {}).items()}
    params = {str(k): str(v) for k, v in (args.params or {}).items()}

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
        try:
            r = await client.request(
                method,
                args.url,
                headers=headers or None,
                params=params or None,
                json=args.json,
                content=(args.body.encode("utf-8") if isinstance(args.body, str) else None),
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    resp_headers: Dict[str, str] = {}
    for k, v in r.headers.items():
        resp_headers[str(k)] = str(v)

    return HttpResponse(status=int(r.status_code), headers=resp_headers, text=r.text)


app = FastAPI(title=APP_NAME, version=APP_VERSION)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "timestampMs": _utc_ms(),
    }


@app.get("/.well-known/mcp.json")
async def well_known() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Allowlisted HTTP client MCP provider (curl-like tools).",
        "capabilities": {"tools": _tool_definitions()},
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": _tool_definitions()}


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args_raw = (payload or {}).get("arguments") or (payload or {}).get("args") or {}

    if tool == "http_get":
        url = str((args_raw or {}).get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="missing_url")
        headers = (args_raw or {}).get("headers") or {}
        params = (args_raw or {}).get("params") or {}
        out = await _do_request(HttpRequestArgs(method="GET", url=url, headers=headers, params=params))
        return {"tool": tool, "result": out.model_dump()}

    if tool == "http_post_json":
        url = str((args_raw or {}).get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="missing_url")
        headers = (args_raw or {}).get("headers") or {}
        params = (args_raw or {}).get("params") or {}
        body_json = (args_raw or {}).get("json")
        out = await _do_request(HttpRequestArgs(method="POST", url=url, headers=headers, params=params, json=body_json))
        return {"tool": tool, "result": out.model_dump()}

    if tool == "http_request":
        parsed = HttpRequestArgs.model_validate(args_raw or {})
        out = await _do_request(parsed)
        return {"tool": tool, "result": out.model_dump()}

    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data)).model_dump(
        exclude_none=True
    )


@app.post("/mcp")
async def mcp(payload: Dict[str, Any] = Body(...)) -> Any:
    request = JsonRpcRequest.model_validate(payload or {})
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

        try:
            if tool_name == "http_get":
                url = str((arguments_raw or {}).get("url") or "").strip()
                if not url:
                    raise HTTPException(status_code=400, detail="missing_url")
                headers = (arguments_raw or {}).get("headers") or {}
                params2 = (arguments_raw or {}).get("params") or {}
                out = await _do_request(HttpRequestArgs(method="GET", url=url, headers=headers, params=params2))
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out.model_dump(), ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "http_post_json":
                url = str((arguments_raw or {}).get("url") or "").strip()
                if not url:
                    raise HTTPException(status_code=400, detail="missing_url")
                headers = (arguments_raw or {}).get("headers") or {}
                params2 = (arguments_raw or {}).get("params") or {}
                body_json = (arguments_raw or {}).get("json")
                out = await _do_request(HttpRequestArgs(method="POST", url=url, headers=headers, params=params2, json=body_json))
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out.model_dump(), ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "http_request":
                parsed = HttpRequestArgs.model_validate(arguments_raw or {})
                out = await _do_request(parsed)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out.model_dump(), ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'")

        except HTTPException as e:
            return _jsonrpc_error(request.id, -32000, str(e.detail), {"status": e.status_code})
        except Exception as e:
            return _jsonrpc_error(request.id, -32000, str(e))

    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'")
