import json
import uuid
from typing import Any, Optional

import httpx
from fastapi import HTTPException


def extract_mcp_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    content = result.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                t = c.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
        return "\n".join(parts).strip()
    t2 = result.get("text")
    if isinstance(t2, str):
        return t2.strip()
    return ""


def mcp_text_json(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return result
    first = content[0] if isinstance(content[0], dict) else None
    if not isinstance(first, dict):
        return result
    text = first.get("text")
    if not isinstance(text, str) or not text.strip():
        return result
    try:
        return json.loads(text)
    except Exception:
        return result


def parse_sse_first_message_data(text: str) -> dict[str, Any]:
    # MCP servers can return multiple SSE events in a single HTTP response.
    # The final JSON-RPC message with the tool call result might not be the first `data:` line.
    last_msg: dict[str, Any] = {}
    for line in (text or "").splitlines():
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :].strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        # Prefer messages that look like real JSON-RPC responses.
        if "result" in parsed or "error" in parsed:
            last_msg = parsed
        elif not last_msg:
            last_msg = parsed
    return last_msg


async def mcp_rpc_base(base_url: str, method: str, params: dict[str, Any]) -> Any:
    session_id = str(uuid.uuid4())
    url = f"{str(base_url or '').rstrip('/')}/mcp?sessionId={session_id}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "jarvis-backend", "version": "0.1"},
            },
        }
        init_res = await client.post(
            url,
            json=init_req,
            headers={"Accept": "application/json, text/event-stream"},
        )
        if init_res.status_code >= 400:
            raise HTTPException(status_code=502, detail={"mcp_initialize_failed": init_res.text})

        mcp_session_id = init_res.headers.get("mcp-session-id") or ""
        if not mcp_session_id:
            raise HTTPException(status_code=502, detail="mcp_missing_session_header")

        req = {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}
        res = await client.post(
            url,
            json=req,
            headers={
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": mcp_session_id,
            },
        )
        if res.status_code >= 400:
            raise HTTPException(status_code=502, detail={"mcp_rpc_failed": res.text})

        # Servers may respond with either:
        # - text/event-stream (SSE): lines like `data: {...}`
        # - application/json: a single JSON-RPC message
        content_type = (res.headers.get("content-type") or "").lower()
        msg: dict[str, Any] = {}
        if "application/json" in content_type:
            try:
                parsed = res.json()
                if isinstance(parsed, dict):
                    msg = parsed
            except Exception:
                msg = {}
        if not msg:
            text = res.text or ""
            # Some servers return JSON even when content-type is not set correctly.
            if text.lstrip().startswith("{"):
                try:
                    parsed2 = json.loads(text)
                    if isinstance(parsed2, dict):
                        msg = parsed2
                except Exception:
                    msg = {}
        if not msg:
            msg = parse_sse_first_message_data(res.text)
        if msg.get("error") is not None:
            raise HTTPException(status_code=502, detail={"mcp_error": msg.get("error")})
        return msg.get("result")


async def mcp_rpc(mcp_base_url: str, method: str, params: dict[str, Any]) -> Any:
    return await mcp_rpc_base(mcp_base_url, method, params)


async def aim_mcp_rpc(aim_mcp_base_url: str, method: str, params: dict[str, Any]) -> Any:
    if not str(aim_mcp_base_url or "").strip():
        raise HTTPException(status_code=500, detail="aim_mcp_base_url_not_configured")
    return await mcp_rpc_base(aim_mcp_base_url, method, params)


async def mcp_tools_list(mcp_base_url: str) -> list[dict[str, Any]]:
    result = await mcp_rpc(mcp_base_url, "tools/list", {})
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return []
    out: list[dict[str, Any]] = []
    for t in tools:
        if isinstance(t, dict) and isinstance(t.get("name"), str):
            out.append(t)
    return out


async def mcp_tools_call(mcp_base_url: str, name: str, arguments: dict[str, Any]) -> Any:
    return await mcp_rpc(mcp_base_url, "tools/call", {"name": name, "arguments": arguments})


async def aim_mcp_tools_call(aim_mcp_base_url: str, name: str, arguments: dict[str, Any]) -> Any:
    return await aim_mcp_rpc(aim_mcp_base_url, "tools/call", {"name": name, "arguments": arguments})
