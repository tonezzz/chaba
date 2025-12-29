import asyncio
import json
import os
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field


def _utc_ts() -> int:
    return int(time.time())


APP_NAME = "mcp-openai-gateway"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8181"))

GLAMA_API_URL = (os.getenv("GLAMA_API_URL") or os.getenv("GLAMA_URL") or "").strip()
GLAMA_API_KEY = (os.getenv("GLAMA_API_KEY") or "").strip()
GLAMA_MODEL_DEFAULT = (os.getenv("GLAMA_MODEL") or "gpt-4o-mini").strip()

MCP_LLM_TOOL_NAME = (os.getenv("OPENAI_GATEWAY_LLM_TOOL") or "").strip()

MCP_AGENT_URL = (
    os.getenv("MCP_AGENT_URL")
    or os.getenv("ONE_MCP_URL")
    or "http://1mcp-agent:3051/mcp?app=openchat"
).strip()

GATEWAY_MODEL_ID = (os.getenv("OPENAI_GATEWAY_MODEL_ID") or "glama-default").strip()

REQUEST_TIMEOUT_SECONDS = float(os.getenv("OPENAI_GATEWAY_TIMEOUT_SECONDS", "60"))

DEBUG = (os.getenv("OPENAI_GATEWAY_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")

PREFER_MCP_LLM = (os.getenv("OPENAI_GATEWAY_PREFER_MCP_LLM") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


app = FastAPI(title=APP_NAME, version=APP_VERSION)


_mcp_session_id: Optional[str] = None
_mcp_session_lock = asyncio.Lock()


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = Field(default=None, alias="max_tokens")
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Any] = None


def _glama_ready() -> bool:
    return bool(GLAMA_API_URL and GLAMA_API_KEY)


def _parse_first_sse_message(text: str) -> Optional[Dict[str, Any]]:
    # Minimal SSE parsing: find the first "data: ..." block and JSON-decode it.
    data_lines: List[str] = []
    in_data = False
    for raw_line in text.splitlines():
        line = raw_line.strip("\r")
        if line.startswith("data:"):
            in_data = True
            data_lines.append(line[len("data:") :].lstrip())
            continue
        if in_data:
            if line == "":
                break
            if line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip())

    if not data_lines:
        return None

    try:
        return json.loads("\n".join(data_lines))
    except Exception:
        return None


async def _mcp_initialize_if_needed() -> Optional[str]:
    global _mcp_session_id
    async with _mcp_session_lock:
        if _mcp_session_id:
            return _mcp_session_id

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": APP_NAME, "version": APP_VERSION},
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            r = await client.post(MCP_AGENT_URL, json=payload, headers=headers)
            r.raise_for_status()

            # 1mcp-agent returns the session id in a response header.
            sid = r.headers.get("mcp-session-id")
            if sid:
                _mcp_session_id = sid

            # MCP spec expects a follow-up notification so the server marks the session initialized.
            if _mcp_session_id:
                notif = {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
                notif_headers = {
                    **headers,
                    "mcp-session-id": _mcp_session_id,
                }
                r2 = await client.post(MCP_AGENT_URL, json=notif, headers=notif_headers)
                r2.raise_for_status()

        return _mcp_session_id


async def _mcp_rpc(method: str, params: Dict[str, Any]) -> Any:
    payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}

    session_id = await _mcp_initialize_if_needed()
    url = MCP_AGENT_URL

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    if session_id:
        headers["mcp-session-id"] = session_id

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        content_type = (r.headers.get("content-type") or "").lower()

        if "text/event-stream" in content_type:
            parsed = _parse_first_sse_message(r.text)
            if not parsed:
                raise RuntimeError("mcp_sse_parse_failed")
            data = parsed
        else:
            data = r.json()

    if data.get("error"):
        raise RuntimeError(data["error"].get("message") or "mcp_error")
    return data.get("result")


async def _mcp_tools_list() -> List[Dict[str, Any]]:
    try:
        res = await _mcp_rpc("tools/list", {})
    except Exception as e:
        if DEBUG:
            print(f"[{APP_NAME}] tools/list failed: {e}")
        return []
    tools = (res or {}).get("tools") or []
    out: List[Dict[str, Any]] = []

    def _sanitize_openai_function_parameters_schema(schema: Any) -> Optional[Dict[str, Any]]:
        # Glama/OpenAI function parameters must be a JSON Schema object.
        # Glama rejects top-level combinators like anyOf/oneOf/allOf as well as enum/not.
        if not isinstance(schema, dict):
            return None
        if schema.get("type") != "object":
            return None
        for bad in ("oneOf", "anyOf", "allOf", "enum", "not"):
            if bad in schema:
                return None
        # Ensure required keys exist.
        if "properties" not in schema or not isinstance(schema.get("properties"), dict):
            schema = dict(schema)
            schema["properties"] = {}
        return schema

    for t in tools:
        name = str(t.get("name") or "").strip()
        if not name:
            continue

        params = _sanitize_openai_function_parameters_schema(
            t.get("inputSchema") or {"type": "object", "properties": {}}
        )
        if not params:
            if DEBUG:
                print(f"[{APP_NAME}] skipping tool with incompatible schema: {name}")
            continue

        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": (t.get("description") or "").strip(),
                    "parameters": params,
                },
            }
        )
    return out


def _tool_result_to_text(result: Any) -> str:
    # 1mcp-agent tools/call returns MCP-style payload:
    # { content: [{type:'text', text:'...'}, ...], isError: bool }
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "\n".join(parts)
    try:
        return json.dumps(result, ensure_ascii=False)
    except Exception:
        return str(result)


def _pick_mcp_llm_tool_name(tools: List[Dict[str, Any]]) -> Optional[str]:
    if MCP_LLM_TOOL_NAME:
        return MCP_LLM_TOOL_NAME

    names: List[str] = []
    for t in tools or []:
        fn = (t or {}).get("function") or {}
        name = str(fn.get("name") or "").strip()
        if name:
            names.append(name)

    for name in names:
        lowered = name.lower()
        if "glama" in lowered and lowered.endswith("chat_completion"):
            return name

    for name in names:
        if name.lower().endswith("chat_completion"):
            return name

    return None


def _messages_for_mcp_llm(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    # mcp-glama only accepts roles: user/assistant/system and requires non-empty content.
    out: List[Dict[str, str]] = []
    for m in messages or []:
        role = str(m.get("role") or "").strip()
        content = m.get("content")
        if role not in ("user", "assistant", "system"):
            continue
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        out.append({"role": role, "content": text})
    return out


async def _mcp_llm_chat(messages: List[Dict[str, Any]], temperature: Optional[float], max_tokens: Optional[int]) -> str:
    tools = await _mcp_tools_list()
    tool_name = _pick_mcp_llm_tool_name(tools)
    if not tool_name:
        raise RuntimeError("mcp_llm_tool_not_found")

    args: Dict[str, Any] = {
        "messages": _messages_for_mcp_llm(messages),
        "model": GLAMA_MODEL_DEFAULT,
    }
    if isinstance(temperature, (int, float)):
        args["temperature"] = float(temperature)
    if isinstance(max_tokens, int) and max_tokens > 0:
        args["max_tokens"] = int(max_tokens)

    result = await _mcp_tools_invoke(tool_name, args)
    return (_tool_result_to_text(result) or "").strip()


async def _mcp_llm_chat_safe(messages: List[Dict[str, Any]], temperature: Optional[float], max_tokens: Optional[int]) -> str:
    try:
        return await _mcp_llm_chat(messages=messages, temperature=temperature, max_tokens=max_tokens)
    except HTTPException:
        raise
    except Exception as e:
        # Avoid leaking low-level stack traces to clients; preserve the reason.
        raise HTTPException(status_code=502, detail=f"mcp_llm_failed: {str(e)}")


async def _mcp_tools_invoke(name: str, arguments: Dict[str, Any]) -> Any:
    res = await _mcp_rpc("tools/call", {"name": name, "arguments": arguments})
    return res


def _build_tool_awareness_system_prompt(tools: List[Dict[str, Any]]) -> str:
    # Keep this short-ish: enough to encourage tool use without blowing context.
    lines: List[str] = []
    lines.append("You have access to external tools (functions).")
    lines.append("Use tools when they would help you answer accurately or fetch/update data.")
    lines.append("If a tool is needed, call it instead of claiming you cannot access external tools.")
    lines.append("If the user asks what tools you have, list the tool names from 'Available tools'.")
    lines.append("Do not claim you lack tool access in this environment.")
    lines.append("")
    lines.append("Available tools:")

    # tools are OpenAI-style: {type:'function', function:{name, description, parameters}}
    for t in tools[:60]:
        fn = (t or {}).get("function") or {}
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        desc = str(fn.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 200:
            desc = desc[:200] + "…"
        if desc:
            lines.append(f"- {name}: {desc}")
        else:
            lines.append(f"- {name}")

    tool_names = {
        str(((t or {}).get("function") or {}).get("name") or "").strip() for t in (tools or [])
    }
    if "create_task" in tool_names and "approve_task" in tool_names:
        lines.append("")
        lines.append("Example: create and execute a task that calls another tool:")
        lines.append(
            "- create_task({title: '...', call: {server: 'mcp-devops', tool: 'run_workflow', args: {workflow_id: 'pc1-caddy-status', dry_run: true}}})"
        )
        lines.append("- approve_task({task_id: '<id>'})")

    return "\n".join(lines).strip()


def _inject_system_prompt(messages: List[Dict[str, Any]], extra_system_text: str) -> List[Dict[str, Any]]:
    if not extra_system_text:
        return messages

    if messages and messages[0].get("role") == "system":
        existing = messages[0].get("content")
        if isinstance(existing, str) and existing.strip():
            messages[0]["content"] = existing.rstrip() + "\n\n" + extra_system_text
        else:
            messages[0]["content"] = extra_system_text
        return messages

    return [{"role": "system", "content": extra_system_text}] + messages


async def _glama_chat(messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], temperature: Optional[float], max_tokens: Optional[int]) -> Dict[str, Any]:
    if not _glama_ready():
        raise HTTPException(status_code=503, detail="glama_unconfigured")

    payload: Dict[str, Any] = {
        "model": GLAMA_MODEL_DEFAULT,
        "messages": messages,
        "temperature": temperature if isinstance(temperature, (int, float)) else 0.2,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GLAMA_API_KEY}"}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        r = await client.post(GLAMA_API_URL, json=payload, headers=headers)
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=r.text or f"glama_http_{r.status_code}")
        return r.json()


def _extract_assistant_message(resp: Dict[str, Any]) -> Dict[str, Any]:
    choices = resp.get("choices") or []
    if not choices:
        raise RuntimeError("glama_missing_choices")
    msg = (choices[0] or {}).get("message") or {}
    return msg


async def _run_tool_loop(initial_messages: List[Dict[str, Any]], temperature: Optional[float], max_tokens: Optional[int]) -> str:
    tools = await _mcp_tools_list()

    messages = list(initial_messages)
    messages = _inject_system_prompt(messages, _build_tool_awareness_system_prompt(tools))
    for _ in range(8):
        resp = await _glama_chat(messages=messages, tools=tools, temperature=temperature, max_tokens=max_tokens)
        assistant = _extract_assistant_message(resp)

        tool_calls = assistant.get("tool_calls") or []
        content = (assistant.get("content") or "").strip() if isinstance(assistant.get("content"), str) else ""

        if tool_calls:
            messages.append({"role": "assistant", "content": assistant.get("content"), "tool_calls": tool_calls})
            for call in tool_calls:
                fn = (call.get("function") or {})
                tool_name = fn.get("name")
                raw_args = fn.get("arguments")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else {}
                except Exception:
                    args = {}

                tool_call_id = call.get("id") or str(uuid.uuid4())
                try:
                    result = await _mcp_tools_invoke(str(tool_name), dict(args))
                    tool_content = _tool_result_to_text(result)
                except Exception as e:
                    err_text = str(e)
                    if DEBUG:
                        tool_content = json.dumps(
                            {
                                "ok": False,
                                "error": err_text,
                                "tool": str(tool_name),
                                "arguments": dict(args),
                            },
                            ensure_ascii=False,
                        )
                    else:
                        tool_content = json.dumps({"ok": False, "error": err_text}, ensure_ascii=False)

                messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": tool_content})
            continue

        if content:
            return content

        return ""

    return ""


def _openai_chat_completion_response(content: str, model: str) -> Dict[str, Any]:
    return {
        "id": f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": _utc_ts(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _sse_frame(obj: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


async def _stream_single_message(content: str, model: str) -> AsyncIterator[bytes]:
    yield _sse_frame(
        {
            "id": f"chatcmpl_{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": _utc_ts(),
            "model": model,
            "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
        }
    )
    yield _sse_frame(
        {
            "id": f"chatcmpl_{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": _utc_ts(),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    )


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok" if _glama_ready() else "degraded",
        "glamaReady": _glama_ready(),
        "timestamp": _utc_ts(),
        "mcpAgentUrl": MCP_AGENT_URL,
    }


@app.get("/debug/mcp")
async def debug_mcp() -> Any:
    if not DEBUG:
        raise HTTPException(status_code=404, detail="not_found")
    return {
        "debug": True,
        "mcpAgentUrl": MCP_AGENT_URL,
        "mcpSessionId": _mcp_session_id,
    }


@app.get("/debug/tools")
async def debug_tools() -> Any:
    if not DEBUG:
        raise HTTPException(status_code=404, detail="not_found")
    tools = await _mcp_tools_list()
    return {
        "debug": True,
        "toolCount": len(tools),
        "tools": tools,
    }


@app.get("/v1/models")
async def list_models() -> Dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": GATEWAY_MODEL_ID,
                "object": "model",
                "created": _utc_ts(),
                "owned_by": "mcp-openai-gateway",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: Request) -> Any:
    try:
        body = await req.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

    parsed = ChatCompletionRequest.model_validate(body)

    # Map the UI-selected model to our backend model. For now we expose a single logical model id.
    _ = parsed.model

    initial_messages = [
        {"role": m.role, "content": m.content, **({"tool_call_id": m.tool_call_id} if m.tool_call_id else {})}
        for m in parsed.messages
    ]

    if PREFER_MCP_LLM:
        content = await _mcp_llm_chat_safe(
            messages=initial_messages,
            temperature=parsed.temperature,
            max_tokens=parsed.max_tokens,
        )
    else:
        if not _glama_ready():
            raise HTTPException(
                status_code=503,
                detail="glama_unconfigured (set GLAMA_API_URL + GLAMA_API_KEY or enable OPENAI_GATEWAY_PREFER_MCP_LLM=1)",
            )
        content = await _run_tool_loop(
            initial_messages=initial_messages,
            temperature=parsed.temperature,
            max_tokens=parsed.max_tokens,
        )

    if parsed.stream:
        return StreamingResponse(
            _stream_single_message(content, model=GATEWAY_MODEL_ID),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    return JSONResponse(_openai_chat_completion_response(content, model=GATEWAY_MODEL_ID))
