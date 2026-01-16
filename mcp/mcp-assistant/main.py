import asyncio
import base64
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Tuple

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI()

logger = logging.getLogger("mcp-assistant")

MCP_ASSISTANT_PORT = int(os.getenv("MCP_ASSISTANT_PORT", "8099"))

# LLM backend (existing pattern)
GLAMA_MCP_URL = (os.getenv("GLAMA_MCP_URL") or "").strip().rstrip("/")
GLAMA_MODEL = (os.getenv("GLAMA_MODEL") or "").strip()
GLAMA_SYSTEM_PROMPT = (os.getenv("GLAMA_SYSTEM_PROMPT") or "").strip()

# 1mcp endpoint for tool invocation
ONE_MCP_URL = (os.getenv("ONE_MCP_URL") or "").strip()
ONE_MCP_BASIC_AUTH = (os.getenv("ONE_MCP_BASIC_AUTH") or "").strip()
ONE_MCP_USERNAME = (os.getenv("ONE_MCP_USERNAME") or "").strip()
ONE_MCP_PASSWORD = (os.getenv("ONE_MCP_PASSWORD") or "").strip()

ONE_MCP_INIT_TIMEOUT_SECONDS = float(os.getenv("ONE_MCP_INIT_TIMEOUT_SECONDS", "30"))
ONE_MCP_REQUEST_TIMEOUT_SECONDS = float(os.getenv("ONE_MCP_REQUEST_TIMEOUT_SECONDS", "600"))

MCP_ASSISTANT_IMAGEN_WIDTH = int(os.getenv("MCP_ASSISTANT_IMAGEN_WIDTH", "512"))
MCP_ASSISTANT_IMAGEN_HEIGHT = int(os.getenv("MCP_ASSISTANT_IMAGEN_HEIGHT", "512"))
MCP_ASSISTANT_IMAGEN_SET_SIZE = str(os.getenv("MCP_ASSISTANT_IMAGEN_SET_SIZE", "true")).strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
)

# Optional shared secret between mcp-line and mcp-assistant
MCP_ASSISTANT_CONTROL_TOKEN = (os.getenv("MCP_ASSISTANT_CONTROL_TOKEN") or "").strip()

# Optional allowlist for safety
MCP_ASSISTANT_ALLOWED_TOOLS = (os.getenv("MCP_ASSISTANT_ALLOWED_TOOLS") or "").strip()
MCP_ASSISTANT_ALLOWED_TOOLS_BY_USER = (os.getenv("MCP_ASSISTANT_ALLOWED_TOOLS_BY_USER") or "").strip()

APP_NAME = "mcp-assistant"
APP_VERSION = "0.1.0"

_messages_by_conversation: Dict[str, List[Dict[str, Any]]] = {}
_max_messages_per_conversation = int(os.getenv("MCP_ASSISTANT_MAX_MESSAGES", "200"))

_imagen_pending_by_conversation: Dict[str, Dict[str, Any]] = {}
_imagen_last_job_by_conversation: Dict[str, Dict[str, str]] = {}
_imagen_expect_refine_by_conversation: Dict[str, bool] = {}
_imagen_jobs_by_conversation: Dict[str, List[Dict[str, Any]]] = {}

_one_mcp_session_by_conversation: Dict[str, str] = {}
_one_mcp_session_locks: Dict[str, asyncio.Lock] = {}


def _utc_ts() -> int:
    return int(time.time())


def _append_message(conversation_id: str, role: str, text: str) -> None:
    cid = str(conversation_id or "").strip()
    if not cid:
        return
    r = str(role or "").strip() or "user"
    t = str(text or "")
    if not t.strip():
        return
    item = {"ts": _utc_ts(), "role": r, "text": t}
    lst = _messages_by_conversation.get(cid)
    if lst is None:
        lst = []
        _messages_by_conversation[cid] = lst
    lst.append(item)
    if len(lst) > _max_messages_per_conversation:
        del lst[: max(0, len(lst) - _max_messages_per_conversation)]


def _list_messages(conversation_id: str, limit: int) -> List[Dict[str, Any]]:
    cid = str(conversation_id or "").strip()
    if not cid:
        return []
    items = _messages_by_conversation.get(cid) or []
    limit = max(1, min(int(limit or 50), 500))
    return items[-limit:]


def _allowed_tools() -> List[str]:
    raw = (MCP_ASSISTANT_ALLOWED_TOOLS or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            import json

            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _parse_tools_list(raw: str) -> List[str]:
    r = (raw or "").strip()
    if not r:
        return []
    if r.startswith("["):
        try:
            import json

            arr = json.loads(r)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            return []
    return [s.strip() for s in r.split(",") if s.strip()]


def _allowed_tools_for_user(user_id: str) -> List[str]:
    base = _allowed_tools()
    raw = (MCP_ASSISTANT_ALLOWED_TOOLS_BY_USER or "").strip()
    if not raw:
        return base

    try:
        import json

        mapping = json.loads(raw)
    except Exception:
        return base

    if not isinstance(mapping, dict):
        return base

    uid = str(user_id or "").strip()
    user_raw: Any = ""
    if uid and uid in mapping:
        user_raw = mapping.get(uid)
    elif "default" in mapping:
        user_raw = mapping.get("default")
    elif "*" in mapping:
        user_raw = mapping.get("*")

    if isinstance(user_raw, list):
        user_tools = [str(x).strip() for x in user_raw if str(x).strip()]
    else:
        user_tools = _parse_tools_list(str(user_raw or ""))

    if not user_tools:
        return base

    if not base:
        return user_tools

    base_set = set(base)
    return [t for t in user_tools if t in base_set]


def _require_control_auth(request: Request) -> None:
    required = MCP_ASSISTANT_CONTROL_TOKEN
    if not required:
        return
    provided = str(request.query_params.get("token") or "").strip()
    if not provided:
        provided = str(request.headers.get("x-control-token") or "").strip()
    if not provided or provided != required:
        raise HTTPException(status_code=401, detail="control_unauthorized")


def _one_mcp_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if ONE_MCP_BASIC_AUTH:
        headers["Authorization"] = f"Basic {ONE_MCP_BASIC_AUTH}"
        return headers
    if ONE_MCP_USERNAME and ONE_MCP_PASSWORD:
        pair = f"{ONE_MCP_USERNAME}:{ONE_MCP_PASSWORD}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(pair).decode("utf-8")
    return headers


def _one_mcp_accept_headers() -> Dict[str, str]:
    return {"Accept": "application/json, text/event-stream"}


def _parse_1mcp_response(resp: httpx.Response) -> Dict[str, Any]:
    ctype = str(resp.headers.get("content-type") or "").lower()
    if ctype.startswith("application/json"):
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {"ok": True, "result": data}
        except Exception:
            return {}

    if "text/event-stream" in ctype:
        text = resp.text or ""
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if not payload:
                    continue
                try:
                    import json

                    obj = json.loads(payload)
                    return obj if isinstance(obj, dict) else {"ok": True, "result": obj}
                except Exception:
                    continue
        return {}

    return {}


def _one_mcp_lock(conversation_id: str) -> asyncio.Lock:
    cid = str(conversation_id or "").strip() or "__default__"
    lock = _one_mcp_session_locks.get(cid)
    if lock is None:
        lock = asyncio.Lock()
        _one_mcp_session_locks[cid] = lock
    return lock


async def _one_mcp_initialize_session(*, conversation_id: str) -> str:
    if not ONE_MCP_URL:
        raise RuntimeError("one_mcp_url_not_configured")

    init_payload: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": APP_NAME, "version": APP_VERSION},
            "capabilities": {},
        },
    }

    async with httpx.AsyncClient(timeout=ONE_MCP_INIT_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            ONE_MCP_URL,
            json=init_payload,
            headers={**_one_mcp_headers(), **_one_mcp_accept_headers()},
        )

    if resp.status_code >= 400:
        detail = (resp.text or "").strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        raise RuntimeError(f"mcp_initialize_failed_{resp.status_code}:{detail}")

    session_id = str(resp.headers.get("mcp-session-id") or "").strip()
    if not session_id:
        raise RuntimeError("mcp_missing_session_id")

    inited_payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}

    async with httpx.AsyncClient(timeout=ONE_MCP_INIT_TIMEOUT_SECONDS) as client:
        resp2 = await client.post(
            ONE_MCP_URL,
            json=inited_payload,
            headers={
                **_one_mcp_headers(),
                **_one_mcp_accept_headers(),
                "mcp-session-id": session_id,
            },
        )

    if resp2.status_code >= 400:
        detail = (resp2.text or "").strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        raise RuntimeError(f"mcp_initialized_failed_{resp2.status_code}:{detail}")

    _one_mcp_session_by_conversation[str(conversation_id or "").strip() or "__default__"] = session_id
    return session_id


async def _one_mcp_get_session_id(*, conversation_id: str) -> str:
    cid = str(conversation_id or "").strip() or "__default__"
    existing = _one_mcp_session_by_conversation.get(cid)
    if existing:
        return existing
    async with _one_mcp_lock(cid):
        existing = _one_mcp_session_by_conversation.get(cid)
        if existing:
            return existing
        return await _one_mcp_initialize_session(conversation_id=cid)


async def _invoke_1mcp(tool: str, arguments: Dict[str, Any], conversation_id: str, user_id: str) -> Dict[str, Any]:
    if not ONE_MCP_URL:
        raise RuntimeError("one_mcp_url_not_configured")

    allowed = _allowed_tools_for_user(user_id)
    if allowed and tool not in allowed:
        raise RuntimeError("tool_not_allowed")

    def _payload(method_name: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method_name,
            "params": {"name": tool, "arguments": arguments or {}},
        }

    payload: Dict[str, Any] = _payload("tools/call")

    async def _do_call(*, session_id: str) -> Tuple[httpx.Response, Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=ONE_MCP_REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                ONE_MCP_URL,
                json=payload,
                headers={
                    **_one_mcp_headers(),
                    **_one_mcp_accept_headers(),
                    "mcp-session-id": session_id,
                },
            )
        data = _parse_1mcp_response(resp)
        return resp, data

    cid = str(conversation_id or "").strip() or "__default__"
    session_id = await _one_mcp_get_session_id(conversation_id=cid)
    resp, data = await _do_call(session_id=session_id)

    if resp.status_code >= 400:
        detail = (resp.text or "").strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        if ("Server not initialized" in detail) or ("No active streamable HTTP session found" in detail):
            _one_mcp_session_by_conversation.pop(cid, None)
            session_id = await _one_mcp_get_session_id(conversation_id=cid)
            resp, data = await _do_call(session_id=session_id)
            if resp.status_code < 400:
                return data
            detail2 = (resp.text or "").strip()
            if len(detail2) > 500:
                detail2 = detail2[:500] + "..."
            raise RuntimeError(f"mcp_call_failed_{resp.status_code}:{detail2}")
        raise RuntimeError(f"mcp_call_failed_{resp.status_code}:{detail}")

    if isinstance(data, dict) and "error" in data:
        err = data.get("error")
        msg = str((err or {}).get("message") or "") if isinstance(err, dict) else str(err)
        # Compatibility: some deployments used tools/invoke; 1mcp uses tools/call.
        if "Method not found" in msg and str((err or {}).get("code") or "") in ("-32601", "-32602"):
            payload = _payload("tools/invoke")
            resp, data = await _do_call(session_id=session_id)
            if isinstance(data, dict) and "error" in data:
                raise RuntimeError(f"mcp_rpc_error:{data.get('error')}")
            return data
        if ("Server not initialized" in msg) or ("No active streamable HTTP session found" in msg):
            _one_mcp_session_by_conversation.pop(cid, None)
            session_id = await _one_mcp_get_session_id(conversation_id=cid)
            resp, data = await _do_call(session_id=session_id)
            if isinstance(data, dict) and "error" in data:
                raise RuntimeError(f"mcp_rpc_error:{data.get('error')}")
            return data
        raise RuntimeError(f"mcp_rpc_error:{err}")

    return data


def _extract_url_from_1mcp_result(res: Dict[str, Any]) -> str:
    url = ""
    if not isinstance(res, dict):
        return ""
    result_obj = res.get("result")
    if isinstance(result_obj, dict):
        url = str(result_obj.get("url") or "").strip()
        if url:
            return url
        url = str(result_obj.get("image_url") or "").strip()
        if url:
            return url
        url = str(result_obj.get("imageUrl") or "").strip()
        if url:
            return url
        content = result_obj.get("content")
        if isinstance(content, list) and content:
            first = content[0] if isinstance(content[0], dict) else {}
            url = str((first or {}).get("url") or "").strip()
            if url:
                return url
            txt = str((first or {}).get("text") or "").strip()
            if txt.startswith("http://") or txt.startswith("https://"):
                return txt
            if txt:
                try:
                    import json

                    maybe = json.loads(txt)
                    if isinstance(maybe, dict):
                        url = str(maybe.get("url") or maybe.get("image_url") or maybe.get("imageUrl") or "").strip()
                        if url:
                            return url
                except Exception:
                    pass
        url = str(result_obj.get("result") or "").strip()
        return url
    return url


def _extract_imagen_job_from_1mcp_result(res: Dict[str, Any]) -> Dict[str, str]:
    if not isinstance(res, dict):
        return {}
    result_obj = res.get("result")
    if not isinstance(result_obj, dict):
        return {}

    job_id = str(result_obj.get("job_id") or result_obj.get("jobId") or "").strip()
    status_url = str(result_obj.get("status_url") or result_obj.get("statusUrl") or "").strip()
    preview_url = str(result_obj.get("preview_url") or result_obj.get("previewUrl") or "").strip()
    result_url = str(result_obj.get("result_url") or result_obj.get("resultUrl") or "").strip()

    if not job_id or not result_url:
        return {}

    return {
        "job_id": job_id,
        "status_url": status_url,
        "preview_url": preview_url,
        "result_url": result_url,
    }


async def _refresh_job_status(job: Dict[str, Any]) -> None:
    url = str(job.get("status_url") or "").strip()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
        if r.status_code >= 400:
            return
        data = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
        if isinstance(data, dict):
            status = str(data.get("status") or "").strip()
            if status:
                job["status"] = status
            progress = data.get("progress")
            if isinstance(progress, dict):
                step = progress.get("step")
                steps = progress.get("steps")
                if step is not None:
                    job["step"] = int(step)
                if steps is not None:
                    job["steps"] = int(steps)
    except Exception:
        return


async def _refresh_job_preview(job: Dict[str, Any]) -> None:
    url = str(job.get("preview_url") or "").strip()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
        if r.status_code >= 400:
            return
        data = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
        if not isinstance(data, dict):
            return
        if data.get("available") is True:
            p_url = str(data.get("url") or data.get("image_url") or "").strip()
            if p_url:
                job["preview"] = p_url
    except Exception:
        return


def _format_jobs_table(jobs: List[Dict[str, Any]]) -> str:
    rows: List[str] = []
    rows.append("job_id\tstatus\tprogress\tpreview")
    for j in jobs:
        jid = str(j.get("job_id") or "").strip()
        st = str(j.get("status") or "").strip() or "unknown"
        step = j.get("step")
        steps = j.get("steps")
        prog = ""
        if step is not None and steps is not None:
            prog = f"{int(step)}/{int(steps)}"
        preview = str(j.get("preview") or "").strip()
        rows.append(f"{jid}\t{st}\t{prog}\t{preview}")
    return "\n".join(rows)[:2000]


async def _glama_chat_completion(prompt: str, system_prompt: str) -> str:
    if not GLAMA_MCP_URL:
        raise RuntimeError("glama_mcp_url_not_configured")

    payload: Dict[str, Any] = {
        "tool": "chat_completion",
        "arguments": {
            "prompt": prompt,
            "system_prompt": system_prompt,
        },
    }
    if GLAMA_MODEL:
        payload["arguments"]["model"] = GLAMA_MODEL

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(GLAMA_MCP_URL, json=payload)

    if resp.status_code >= 400:
        raise RuntimeError(f"glama_http_{resp.status_code}")

    data = resp.json() if resp.headers.get("content-type", "").lower().startswith("application/json") else {}
    result = (data or {}).get("result") or {}
    return str((result or {}).get("response") or "").strip()


async def _agent_reply(*, text: str, conversation_id: str, user_id: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        return {"reply_type": "text", "text": "ok"}

    if cleaned.lower().startswith("imagen:"):
        cleaned = "imagen " + cleaned[len("imagen:") :].lstrip()

    _append_message(conversation_id, "user", cleaned)

    lowered = cleaned.lower()

    cid = str(conversation_id or "").strip() or "__default__"
    if _imagen_expect_refine_by_conversation.get(cid):
        if lowered.startswith("imagen "):
            new_prompt = cleaned[len("imagen ") :].strip()
        else:
            new_prompt = cleaned
        if new_prompt:
            _imagen_expect_refine_by_conversation[cid] = False
            pending = {
                "prompt": new_prompt,
                "width": int(MCP_ASSISTANT_IMAGEN_WIDTH) if MCP_ASSISTANT_IMAGEN_SET_SIZE else None,
                "height": int(MCP_ASSISTANT_IMAGEN_HEIGHT) if MCP_ASSISTANT_IMAGEN_SET_SIZE else None,
                "updatedAt": _utc_ts(),
            }
            _imagen_pending_by_conversation[cid] = pending
            msg = "Ready. Click: imagen approve / imagen cancel / imagen status / imagen help"
            out = {"reply_type": "text", "text": msg}
            _append_message(conversation_id, "assistant", out["text"])
            return out

    if lowered == "imagen" or lowered.startswith("imagen "):
        cmd = lowered
        rest = ""
        if cmd != "imagen":
            rest = cleaned[len("imagen ") :].strip()
            cmd = "imagen " + rest.lower()

        if cmd in ("imagen help",):
            msg = (
                "Imagen menu commands:\n"
                "- imagen <prompt>: set prompt (no generation yet)\n"
                "- imagen approve: start generation\n"
                "- imagen refine: replace prompt\n"
                "- imagen status: show last job\n"
                "- imagen cancel: clear pending\n"
                "- imagen clear: clear cached jobs"
            )
            out = {"reply_type": "text", "text": msg}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen cancel",):
            _imagen_pending_by_conversation.pop(cid, None)
            _imagen_expect_refine_by_conversation[cid] = False
            out = {"reply_type": "text", "text": "Canceled."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen clear", "imagen reset"):
            _imagen_pending_by_conversation.pop(cid, None)
            _imagen_expect_refine_by_conversation[cid] = False
            _imagen_jobs_by_conversation.pop(cid, None)
            _imagen_last_job_by_conversation.pop(cid, None)
            out = {"reply_type": "text", "text": "Cleared imagen state."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen refine",):
            _imagen_expect_refine_by_conversation[cid] = True
            out = {"reply_type": "text", "text": "Send the new prompt (either plain text or 'imagen <prompt>')."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen status",):
            jobs = list(_imagen_jobs_by_conversation.get(cid) or [])
            if not jobs:
                last = _imagen_last_job_by_conversation.get(cid) or {}
                if last:
                    jobs = [dict(last)]
            if not jobs:
                out = {"reply_type": "text", "text": "No image job yet."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            jobs = jobs[-10:]
            for j in jobs:
                await _refresh_job_status(j)
                await _refresh_job_preview(j)
            out = {"reply_type": "text", "text": _format_jobs_table(jobs)}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen approve",):
            pending = _imagen_pending_by_conversation.get(cid) or {}
            prompt = str(pending.get("prompt") or "").strip()
            if not prompt:
                out = {"reply_type": "text", "text": "No pending prompt. Send: imagen <prompt>"}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            tool_name = "mcp-imagen-light_1mcp_imagen_generate"
            allowed = _allowed_tools_for_user(user_id)
            if allowed and tool_name not in allowed:
                out = {"reply_type": "text", "text": "Image tool not allowed."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            args: Dict[str, Any] = {"prompt": prompt}
            if MCP_ASSISTANT_IMAGEN_SET_SIZE:
                args["width"] = int(MCP_ASSISTANT_IMAGEN_WIDTH)
                args["height"] = int(MCP_ASSISTANT_IMAGEN_HEIGHT)
            args["approved"] = True
            try:
                res = await _invoke_1mcp(tool_name, args, conversation_id, user_id)
                job = _extract_imagen_job_from_1mcp_result(res)
                if job:
                    record: Dict[str, Any] = {**job, "status": "submitted", "createdAt": _utc_ts()}
                    lst = _imagen_jobs_by_conversation.get(cid)
                    if lst is None:
                        lst = []
                        _imagen_jobs_by_conversation[cid] = lst
                    lst.append(record)
                    if len(lst) > 50:
                        del lst[: max(0, len(lst) - 50)]
                    _imagen_last_job_by_conversation[cid] = job
                    _imagen_pending_by_conversation.pop(cid, None)
                    out = {
                        "reply_type": "image_job",
                        "text": "Image job started.",
                        **job,
                    }
                    _append_message(conversation_id, "assistant", out["text"])
                    return out
                url = _extract_url_from_1mcp_result(res)
                if url:
                    _imagen_pending_by_conversation.pop(cid, None)
                    out = {"reply_type": "image", "text": url, "url": url}
                    _append_message(conversation_id, "assistant", url)
                    return out
                out = {"reply_type": "text", "text": "Started, but no job info returned."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            except Exception as exc:
                msg = str(exc)
                logger.warning("imagen_call_failed: %s", msg)
                out = {"reply_type": "text", "text": f"Image generation failed: {msg}"}
                _append_message(conversation_id, "assistant", out["text"][:2000])
                return out

        if rest:
            pending = {
                "prompt": rest,
                "width": int(MCP_ASSISTANT_IMAGEN_WIDTH) if MCP_ASSISTANT_IMAGEN_SET_SIZE else None,
                "height": int(MCP_ASSISTANT_IMAGEN_HEIGHT) if MCP_ASSISTANT_IMAGEN_SET_SIZE else None,
                "updatedAt": _utc_ts(),
            }
            _imagen_pending_by_conversation[cid] = pending
            msg = "Ready. Click: imagen approve / imagen refine / imagen cancel / imagen status / imagen help"
            out = {"reply_type": "text", "text": msg}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        pending = _imagen_pending_by_conversation.get(cid) or {}
        prompt = str(pending.get("prompt") or "").strip()
        if prompt:
            out = {"reply_type": "text", "text": "Pending prompt exists. Click: imagen approve / imagen refine / imagen cancel"}
        else:
            out = {"reply_type": "text", "text": "Send: imagen <prompt>"}
        _append_message(conversation_id, "assistant", out["text"])
        return out
    wants_image = any(
        k in lowered
        for k in (
            "generate an image",
            "generate image",
            "create an image",
            "make an image",
            "image of",
            "create a picture",
            "generate a picture",
        )
    )

    if wants_image:
        pending = {
            "prompt": cleaned,
            "width": int(MCP_ASSISTANT_IMAGEN_WIDTH) if MCP_ASSISTANT_IMAGEN_SET_SIZE else None,
            "height": int(MCP_ASSISTANT_IMAGEN_HEIGHT) if MCP_ASSISTANT_IMAGEN_SET_SIZE else None,
            "updatedAt": _utc_ts(),
        }
        _imagen_pending_by_conversation[cid] = pending
        out = {
            "reply_type": "text",
            "text": "Ready. Click: imagen approve / imagen refine / imagen cancel / imagen status / imagen help",
        }
        _append_message(conversation_id, "assistant", out["text"])
        return out

    # For now: single-step tool choice.
    # Output must be STRICT JSON. This is intentionally narrow for dev stability.
    system_prompt = (
        (GLAMA_SYSTEM_PROMPT.strip() + "\n\n" if GLAMA_SYSTEM_PROMPT.strip() else "")
        + "You are an assistant that can call tools via 1mcp. Respond with ONLY valid JSON. "
        + "Choose exactly one action. Allowed actions: reply_text, call_tool. "
        + "Schemas: "
        + '{"action":"reply_text","text":string} '
        + 'OR {"action":"call_tool","tool":string,"arguments":object,"explain":string}. '
        + "If a tool call would help, choose call_tool. Otherwise reply_text. "
        + "Keep replies concise."
    )

    llm_out = await _glama_chat_completion(prompt=cleaned, system_prompt=system_prompt)

    try:
        import json

        obj = json.loads(llm_out)
    except Exception:
        return {"reply_type": "text", "text": llm_out[:2000] or "ok"}

    if not isinstance(obj, dict):
        return {"reply_type": "text", "text": llm_out[:2000] or "ok"}

    action = str(obj.get("action") or "").strip()
    if action == "reply_text":
        t = str(obj.get("text") or "").strip() or "ok"
        out = {"reply_type": "text", "text": t[:2000]}
        _append_message(conversation_id, "assistant", out["text"])
        return out

    if action == "call_tool":
        tool = str(obj.get("tool") or "").strip()
        args = obj.get("arguments") if isinstance(obj.get("arguments"), dict) else {}
        explain = str(obj.get("explain") or "").strip()

        if not tool:
            return {"reply_type": "text", "text": "Missing tool name."}

        res = await _invoke_1mcp(tool, args, conversation_id, user_id)
        url = _extract_url_from_1mcp_result(res)

        # If tool produced a URL (common for imagen/quickchart), expose it.
        if url:
            out = {
                "reply_type": "image",
                "text": (explain + "\n" if explain else "") + url,
                "url": url,
            }
            _append_message(conversation_id, "assistant", str(out.get("text") or "")[:2000])
            return out

        # Fallback: summarize JSON (bounded)
        summary = ""
        try:
            import json

            summary = json.dumps(res, ensure_ascii=False)[:1800]
        except Exception:
            summary = str(res)[:1800]

        if explain:
            summary = explain + "\n" + summary

        out = {"reply_type": "text", "text": summary}
        _append_message(conversation_id, "assistant", str(out.get("text") or "")[:2000])
        return out

    out = {"reply_type": "text", "text": llm_out[:2000] or "ok"}
    _append_message(conversation_id, "assistant", str(out.get("text") or "")[:2000])
    return out


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": APP_NAME,
        "version": APP_VERSION,
        "glamaMcpUrl": GLAMA_MCP_URL,
        "oneMcpUrl": ONE_MCP_URL,
        "allowedTools": _allowed_tools(),
    }


class InvokePayload(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


def _tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "chat_new_conversation",
            "description": "Create a new conversation id for mcp-assistant chat.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "chat_post_message",
            "description": "Append a message to a conversation. This does not call the LLM.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string"},
                    "role": {"type": "string", "description": "user|assistant|system"},
                    "text": {"type": "string"},
                },
                "required": ["conversation_id", "text"],
            },
        },
        {
            "name": "chat_list_messages",
            "description": "List recent messages for a conversation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["conversation_id"],
            },
        },
        {
            "name": "chat_send",
            "description": "Send a user message into the assistant (LLM + optional tool call) and return the reply.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
        },
    ]


@app.get("/.well-known/mcp.json")
async def well_known() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Agent runtime + chat UI. Exposes chat tools for programmatic access.",
        "capabilities": {"tools": _tool_definitions()},
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": _tool_definitions()}


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args = (payload or {}).get("arguments") or (payload or {}).get("args") or {}

    if tool == "chat_new_conversation":
        cid = str(uuid.uuid4())
        _messages_by_conversation[cid] = []
        return {"tool": tool, "result": {"conversation_id": cid}}

    if tool == "chat_post_message":
        conversation_id = str((args or {}).get("conversation_id") or "").strip()
        text = str((args or {}).get("text") or "")
        role = str((args or {}).get("role") or "user").strip() or "user"
        if not conversation_id:
            raise HTTPException(status_code=400, detail="missing_conversation_id")
        if not text.strip():
            raise HTTPException(status_code=400, detail="missing_text")
        _append_message(conversation_id, role, text)
        return {"tool": tool, "result": {"ok": True}}

    if tool == "chat_list_messages":
        conversation_id = str((args or {}).get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="missing_conversation_id")
        limit = int((args or {}).get("limit") or 50)
        return {
            "tool": tool,
            "result": {"conversation_id": conversation_id, "items": _list_messages(conversation_id, limit)},
        }

    if tool == "chat_send":
        conversation_id = str((args or {}).get("conversation_id") or "").strip() or str(uuid.uuid4())
        user_id = str((args or {}).get("user_id") or "").strip() or conversation_id
        text = str((args or {}).get("text") or "")
        if not text.strip():
            raise HTTPException(status_code=400, detail="missing_text")
        reply = await _agent_reply(text=text, conversation_id=conversation_id, user_id=user_id)
        return {"tool": tool, "result": {"conversation_id": conversation_id, **reply}}

    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


@app.post("/chat")
async def chat(request: Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")
    conversation_id = str((body or {}).get("conversation_id") or "").strip() or str(uuid.uuid4())
    user_id = str((body or {}).get("user_id") or "").strip() or conversation_id
    text = str((body or {}).get("text") or "")

    try:
        reply = await _agent_reply(text=text, conversation_id=conversation_id, user_id=user_id)
        return {"ok": True, "conversation_id": conversation_id, **reply}
    except Exception as exc:
        logger.warning("chat_failed: %s", str(exc))
        return {"ok": False, "conversation_id": conversation_id, "reply_type": "text", "text": "Error."}


@app.post("/integrations/line/reply")
async def integrations_line_reply(request: Request) -> Dict[str, Any]:
    _require_control_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    conversation_id = str((body or {}).get("conversation_id") or "").strip() or str(uuid.uuid4())
    user_text = str((body or {}).get("text") or "")
    line_event = (body or {}).get("line_event") or {}
    user_id = ""
    try:
        src = (line_event or {}).get("source") or {}
        if isinstance(src, dict):
            user_id = str(src.get("userId") or "").strip()
    except Exception:
        user_id = ""
    if not user_id:
        user_id = conversation_id

    try:
        reply = await _agent_reply(text=user_text, conversation_id=conversation_id, user_id=user_id)
    except Exception as exc:
        logger.warning("line_reply_failed: %s", str(exc))
        reply = {"reply_type": "text", "text": "Sorry, I had an error while processing that."}

    # Convert to LINE Messaging API message objects
    if reply.get("reply_type") == "image" and str(reply.get("url") or "").strip():
        url = str(reply.get("url") or "").strip()
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "messages": [
                {
                    "type": "image",
                    "originalContentUrl": url,
                    "previewImageUrl": url,
                }
            ],
        }

    if reply.get("reply_type") == "image_job" and str(reply.get("job_id") or "").strip():
        job = {
            "job_id": str(reply.get("job_id") or "").strip(),
            "status_url": str(reply.get("status_url") or "").strip(),
            "preview_url": str(reply.get("preview_url") or "").strip(),
            "result_url": str(reply.get("result_url") or "").strip(),
        }
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "messages": [{"type": "text", "text": str(reply.get("text") or "Image job started.")[:2000]}],
            "image_job": job,
        }

    text_out = str(reply.get("text") or "ok")
    if len(text_out) > 2000:
        text_out = text_out[:2000]

    return {"ok": True, "conversation_id": conversation_id, "messages": [{"type": "text", "text": text_out}]}
