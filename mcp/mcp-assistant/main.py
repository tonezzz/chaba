import asyncio
import base64
import io
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Tuple

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image
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

_imagen_jobs_by_conversation: Dict[str, List[Dict[str, Any]]] = {}
_imagen_pending_by_conversation: Dict[str, Dict[str, Any]] = {}
_imagen_expect_refine_by_conversation: Dict[str, bool] = {}
_imagen_expect_ref_image_by_conversation: Dict[str, bool] = {}
_imagen_last_job_by_conversation: Dict[str, Dict[str, Any]] = {}

_imagen_presets_by_user: Dict[str, Dict[str, Dict[str, Any]]] = {}
_imagen_expect_apply_extracted_by_conversation: Dict[str, bool] = {}
_imagen_extracted_diff_by_conversation: Dict[str, Dict[str, Any]] = {}

_imagen_expect_prompt_by_conversation: Dict[str, bool] = {}
_imagen_expect_neg_by_conversation: Dict[str, bool] = {}

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


def _line_quick_reply_item(label: str, text: str) -> Dict[str, Any]:
    lab = str(label or "").strip()
    txt = str(text or "").strip()
    if len(lab) > 20:
        lab = lab[:20]
    if len(txt) > 300:
        txt = txt[:300]
    return {"type": "action", "action": {"type": "message", "label": lab or "OK", "text": txt or "ok"}}


def _line_menu_message(text: str, items: List[Tuple[str, str]]) -> Dict[str, Any]:
    qr_items: List[Dict[str, Any]] = []
    for label, cmd in items[:13]:
        qr_items.append(_line_quick_reply_item(label, cmd))
    return {"type": "text", "text": str(text or "")[:2000], "quickReply": {"items": qr_items}}


def _imagen_ready_state(pending: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(pending) if isinstance(pending, dict) else {}
    prompt = str(p.get("prompt") or "").strip()
    return {
        "has_prompt": bool(prompt),
        "has_ref": bool(str(p.get("referenceImageBase64") or "").strip()),
        "model": str(p.get("imagenModel") or "").strip(),
        "steps": p.get("numInferenceSteps"),
        "seed": p.get("seed"),
    }


def _imagen_status_text(*, pending: Dict[str, Any], last_job: Dict[str, Any], jobs_count: int) -> str:
    st = _imagen_ready_state(pending)
    lines: List[str] = []
    lines.append("Imagen")
    lines.append(f"prompt: {'set' if st['has_prompt'] else '(missing)'}")
    if st.get("model"):
        lines.append(f"model: {st['model']}")
    if st.get("steps") is not None:
        lines.append(f"steps: {st['steps']}")
    if st.get("seed") is not None:
        lines.append(f"seed: {st['seed']}")
    lines.append(f"ref: {'set' if st['has_ref'] else '(none)'}")
    if isinstance(last_job, dict) and str(last_job.get("job_id") or "").strip():
        lines.append(f"last_job: {str(last_job.get('job_id') or '').strip()}")
    if isinstance(jobs_count, int) and jobs_count > 0:
        lines.append(f"jobs: {jobs_count}")

    next_action = ""
    if not st.get("has_prompt"):
        next_action = "Next: imagen prompt <text>"
    else:
        if st.get("has_ref"):
            next_action = "Next: imagen run"
        else:
            next_action = "Next: imagen run (or imagen ref)"
    lines.append(next_action)
    return "\n".join(lines)[:2000]


def _parse_imagen_inline_params(text: str) -> Tuple[str, Dict[str, Any]]:
    raw = str(text or "")
    cleaned = raw
    updates: Dict[str, Any] = {}

    def _take_int(key: str, target: str) -> None:
        nonlocal cleaned
        m = re.search(rf"(?i)\\b{re.escape(key)}\\s*=\\s*(\\d+)\\b", cleaned)
        if not m:
            return
        try:
            updates[target] = int(m.group(1))
        except Exception:
            return
        cleaned = re.sub(rf"(?i)\\b{re.escape(key)}\\s*=\\s*\\d+\\b", "", cleaned).strip()

    def _take_str(key: str, target: str) -> None:
        nonlocal cleaned
        m = re.search(rf"(?i)\\b{re.escape(key)}\\s*=\\s*([^\\s].*?)($|\\s(?=[A-Za-z_]+\\s*=))", cleaned)
        if not m:
            return
        val = str(m.group(1) or "").strip().strip('"')
        if not val:
            return
        updates[target] = val
        cleaned = cleaned.replace(m.group(0), " ").strip()

    _take_int("steps", "numInferenceSteps")
    _take_int("seed", "seed")
    _take_str("model", "imagenModel")
    _take_str("neg", "negativePrompt")
    _take_str("negative", "negativePrompt")

    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, updates


def _diff_pending(before: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    b = dict(before) if isinstance(before, dict) else {}
    diffs: Dict[str, Any] = {}
    for k, v in (updates or {}).items():
        if b.get(k) != v:
            diffs[k] = {"from": b.get(k), "to": v}
    return diffs


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


def _imagen_poll_base_url() -> str:
    return str(os.getenv("MCP_ASSISTANT_IMAGEN_POLL_BASE_URL", "http://mcp-imagen-light:8020") or "").strip().rstrip("/")


def _imagen_public_base_url() -> str:
    return str(os.getenv("MCP_ASSISTANT_IMAGEN_PUBLIC_BASE_URL", "http://10.8.0.1:8068") or "").strip().rstrip("/")


def _rewrite_imagen_url(url: str, base: str) -> str:
    u = str(url or "").strip()
    b = str(base or "").strip().rstrip("/")
    if not u or not b:
        return u

    if "/imagen/" not in u:
        return u

    if u.startswith(b + "/"):
        return u

    if u.startswith("https://line.idc1.surf-thailand.com/") or u.startswith("http://line.idc1.surf-thailand.com/"):
        idx = u.find("/imagen/")
        if idx >= 0:
            return b + u[idx:]
        return u

    return u


def _imagen_public_image_urls(job_id: str) -> Dict[str, str]:
    jid = str(job_id or "").strip()
    base = _imagen_public_base_url()
    if not jid or not base:
        return {"preview": "", "result": ""}
    return {
        "preview": f"{base}/images/preview_{jid}.png",
        "result": f"{base}/images/{jid}.png",
    }


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
    url = _rewrite_imagen_url(url, _imagen_poll_base_url())
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
        if r.status_code == 404:
            job["status"] = "not_found"
            job["error"] = "job_not_found"
            return
        if r.status_code == 409:
            # not submitted / not ready yet
            job["status"] = job.get("status") or "submitted"
            return
        if r.status_code >= 400:
            body_txt = (r.text or "")[:800]
            if "job_not_found" in body_txt or "cuda_job_not_found" in body_txt:
                job["status"] = "not_found"
                job["error"] = "job_not_found"
            elif body_txt:
                job["error"] = body_txt
            return
        data = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
        if isinstance(data, dict):
            status = str(data.get("status") or "").strip()
            if status:
                job["status"] = status
            err = data.get("error")
            if err is not None:
                job["error"] = err
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
    url = _rewrite_imagen_url(url, _imagen_poll_base_url())
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
        if r.status_code == 404:
            if str(job.get("status") or "").strip() not in ("succeeded", "failed"):
                job["status"] = "not_found"
                job["error"] = job.get("error") or "job_not_found"
            return
        if r.status_code >= 400:
            body_txt = (r.text or "")[:800]
            if "not_found" in body_txt or "job_not_found" in body_txt:
                if str(job.get("status") or "").strip() not in ("succeeded", "failed"):
                    job["status"] = "not_found"
                    job["error"] = job.get("error") or "job_not_found"
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


async def _refresh_job_result(job: Dict[str, Any]) -> None:
    url = str(job.get("result_url") or "").strip()
    url = _rewrite_imagen_url(url, _imagen_poll_base_url())
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
        if r.status_code == 404:
            if str(job.get("status") or "").strip() not in ("succeeded", "failed"):
                job["status"] = "not_found"
                job["error"] = job.get("error") or "job_not_found"
            return
        if r.status_code >= 400:
            body_txt = (r.text or "")[:800]
            if "not_found" in body_txt or "job_not_found" in body_txt:
                if str(job.get("status") or "").strip() not in ("succeeded", "failed"):
                    job["status"] = "not_found"
                    job["error"] = job.get("error") or "job_not_found"
            return
        data = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
        if not isinstance(data, dict):
            return
        if data.get("available") is True:
            final_url = str(data.get("url") or data.get("image_url") or "").strip()
            if final_url:
                job["result"] = final_url
    except Exception:
        return


def _format_jobs_table(jobs: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for j in jobs:
        jid = str(j.get("job_id") or "").strip() or "(unknown_job_id)"
        st = str(j.get("status") or "").strip() or "unknown"
        step = j.get("step")
        steps = j.get("steps")
        prog = ""
        if step is not None and steps is not None:
            prog = f"{int(step)}/{int(steps)}"

        err = j.get("error")
        preview = str(j.get("preview") or "").strip()
        result = str(j.get("result") or "").strip()
        status_url = _rewrite_imagen_url(str(j.get("status_url") or "").strip(), _imagen_public_base_url())
        preview_url = _rewrite_imagen_url(str(j.get("preview_url") or "").strip(), _imagen_public_base_url())
        result_url = _rewrite_imagen_url(str(j.get("result_url") or "").strip(), _imagen_public_base_url())
        img_urls = _imagen_public_image_urls(jid if jid != "(unknown_job_id)" else "")
        preview_img_url = str(img_urls.get("preview") or "").strip()
        result_img_url = str(img_urls.get("result") or "").strip()

        width = j.get("width")
        height = j.get("height")
        seed = j.get("seed")
        num_steps = j.get("numInferenceSteps") or j.get("num_inference_steps")

        lines.append(f"job: {jid}")
        lines.append(f"status: {st}" + (f" ({prog})" if prog else ""))
        if st in ("not_found", "expired"):
            lines.append("note: job not found (likely mcp-cuda restarted). Send: imagen clear")
        if err:
            lines.append(f"error: {str(err)[:300]}")
        if width and height:
            lines.append(f"size: {width}x{height}")
        if num_steps:
            lines.append(f"steps: {num_steps}")
        if seed is not None and str(seed).strip() != "":
            lines.append(f"seed: {seed}")
        if preview:
            lines.append(f"preview_image_url: {preview}")
        elif preview_img_url:
            lines.append(f"preview_image_url: {preview_img_url}")
        if result:
            lines.append(f"result_image_url: {result}")
        elif result_img_url:
            lines.append(f"result_image_url: {result_img_url}")
        if status_url:
            lines.append(f"status_url: {status_url}")
        if preview_url:
            lines.append(f"api_preview_url: {preview_url}")
        if result_url:
            lines.append(f"api_result_url: {result_url}")
        lines.append("---")

        if len("\n".join(lines)) > 1800:
            break

    out = "\n".join(lines).rstrip("-\n ")
    return out[:2000]


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

    if lowered in ("menu", "help", "commands", "imagen menu"):
        menu_msg = {
            "type": "text",
            "text": "Menu",
            "quickReply": {
                "items": [
                    {"type": "action", "action": {"type": "message", "label": "Imagen help", "text": "imagen help"}},
                    {"type": "action", "action": {"type": "message", "label": "Imagen status", "text": "imagen status"}},
                    {"type": "action", "action": {"type": "message", "label": "Set steps 40", "text": "imagen steps 40"}},
                    {"type": "action", "action": {"type": "message", "label": "Approve", "text": "imagen approve"}},
                    {"type": "action", "action": {"type": "message", "label": "Cancel", "text": "imagen cancel"}},
                ]
            },
        }
        out = {"reply_type": "line_messages", "messages": [menu_msg]}
        _append_message(conversation_id, "assistant", "Menu")
        return out

    cid = str(conversation_id or "").strip() or "__default__"

    def _merge_imagen_pending(*, updates: Dict[str, Any]) -> Dict[str, Any]:
        base = _imagen_pending_by_conversation.get(cid) or {}
        base = dict(base) if isinstance(base, dict) else {}
        for k, v in (updates or {}).items():
            base[k] = v
        if MCP_ASSISTANT_IMAGEN_SET_SIZE:
            if base.get("width") is None:
                base["width"] = int(MCP_ASSISTANT_IMAGEN_WIDTH)
            if base.get("height") is None:
                base["height"] = int(MCP_ASSISTANT_IMAGEN_HEIGHT)
        base["updatedAt"] = _utc_ts()
        _imagen_pending_by_conversation[cid] = base
        return base

    def _menu_default() -> Dict[str, Any]:
        pending = _imagen_pending_by_conversation.get(cid) or {}
        last = _imagen_last_job_by_conversation.get(cid) or {}
        jobs = _imagen_jobs_by_conversation.get(cid) or []
        text = _imagen_status_text(pending=pending, last_job=last, jobs_count=len(jobs))
        msg = _line_menu_message(
            text,
            [
                ("Prompt", "imagen prompt"),
                ("Ref", "imagen ref"),
                ("Run", "imagen run"),
                ("Neg", "imagen neg"),
                ("Steps", "imagen steps"),
                ("Seed", "imagen seed"),
                ("Model", "imagen model"),
                ("Jobs", "imagen jobs"),
                ("Preset", "imagen preset list"),
                ("Reset", "imagen reset"),
                ("Help", "imagen help"),
                ("Sum", "imagen sum"),
                ("Show", "imagen show"),
            ],
        )
        out = {"reply_type": "line_messages", "messages": [msg]}
        _append_message(conversation_id, "assistant", str(msg.get("text") or "")[:2000])
        return out

    # If we're waiting for the user to send the prompt/negative prompt as the next message,
    # capture it here before falling through to the generic LLM path.
    if _imagen_expect_prompt_by_conversation.get(cid) and not lowered.startswith("imagen "):
        _imagen_expect_prompt_by_conversation[cid] = False
        prompt_clean, extracted = _parse_imagen_inline_params(cleaned)
        before = _imagen_pending_by_conversation.get(cid) or {}
        before = dict(before) if isinstance(before, dict) else {}
        _merge_imagen_pending(updates={"prompt": prompt_clean})
        if extracted:
            diff = _diff_pending(before, extracted)
            if diff:
                _imagen_expect_apply_extracted_by_conversation[cid] = True
                _imagen_extracted_diff_by_conversation[cid] = diff
                lines = ["Extracted params:"]
                for k, d in diff.items():
                    lines.append(f"- {k}: {d.get('from')} -> {d.get('to')}")
                menu_msg = _line_menu_message("\n".join(lines), [("Apply", "imagen apply"), ("Discard", "imagen discard"), ("Run", "imagen run")])
                out = {"reply_type": "line_messages", "messages": [menu_msg]}
                _append_message(conversation_id, "assistant", "Extracted params")
                return out
        out = {"reply_type": "text", "text": "OK. Prompt set. Send: imagen run"}
        _append_message(conversation_id, "assistant", out["text"])
        return out

    if _imagen_expect_neg_by_conversation.get(cid) and not lowered.startswith("imagen "):
        _imagen_expect_neg_by_conversation[cid] = False
        _merge_imagen_pending(updates={"negativePrompt": cleaned})
        out = {"reply_type": "text", "text": "OK. Negative prompt set."}
        _append_message(conversation_id, "assistant", out["text"])
        return out

    if _imagen_expect_refine_by_conversation.get(cid):
        if lowered.startswith("imagen "):
            new_prompt = cleaned[len("imagen ") :].strip()
        else:
            new_prompt = cleaned
        if new_prompt:
            _imagen_expect_refine_by_conversation[cid] = False
            _merge_imagen_pending(updates={"prompt": new_prompt})
            msg = "Ready. Click: imagen approve / imagen cancel / imagen status / imagen help"
            out = {"reply_type": "text", "text": msg}
            _append_message(conversation_id, "assistant", out["text"])
            return out

    if lowered in ("imagen ref", "imagen reference"):
        _imagen_expect_ref_image_by_conversation[cid] = True
        out = {"reply_type": "text", "text": "OK. Please send a reference image now."}
        _append_message(conversation_id, "assistant", out["text"])
        return out

    if lowered in ("imagen ref clear", "imagen ref remove"):
        pending = _imagen_pending_by_conversation.get(cid) or {}
        pending = dict(pending) if isinstance(pending, dict) else {}
        if not str(pending.get("referenceImageBase64") or "").strip():
            out = {"reply_type": "text", "text": "No reference image set."}
            _append_message(conversation_id, "assistant", out["text"])
            return out
        pending.pop("referenceImageBase64", None)
        pending.pop("referenceImageMimeType", None)
        pending.pop("referenceImageDimensions", None)
        pending["updatedAt"] = _utc_ts()
        _imagen_pending_by_conversation[cid] = pending
        out = {"reply_type": "text", "text": "OK. Reference image cleared."}
        _append_message(conversation_id, "assistant", out["text"])
        return out

    if lowered in ("imagen models", "imagen model"):
        tool_name = "mcp-cuda_1mcp_imagen_models"
        allowed = _allowed_tools_for_user(user_id)
        if allowed and tool_name not in allowed:
            out = {"reply_type": "text", "text": "Model listing tool not allowed."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        try:
            res = await _invoke_1mcp(tool_name, {}, conversation_id, user_id)
        except Exception as exc:
            out = {"reply_type": "text", "text": f"Failed to list models: {exc}"}
            _append_message(conversation_id, "assistant", out["text"][:2000])
            return out

        raw = (res or {}).get("result")
        if not isinstance(raw, dict):
            # Some 1mcp responses wrap the output in content/text; keep fallback simple.
            out = {"reply_type": "text", "text": "No model list returned."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        sd15_models = raw.get("sd15_models")
        models: List[str] = []
        if isinstance(sd15_models, list):
            for m in sd15_models:
                if isinstance(m, dict):
                    name = str(m.get("name") or "").strip()
                    if name:
                        models.append(name)
                elif isinstance(m, str):
                    models.append(m)

        # LINE quickReply is limited; keep it small.
        items: List[Dict[str, Any]] = []
        items.append({"type": "action", "action": {"type": "message", "label": "SDXL", "text": "imagen model sdxl"}})
        for name in models[:12]:
            label = name
            if len(label) > 20:
                label = label[:20]
            items.append({"type": "action", "action": {"type": "message", "label": label, "text": f"imagen model {name}"}})

        menu_msg = {"type": "text", "text": "Pick model:", "quickReply": {"items": items}}
        out = {"reply_type": "line_messages", "messages": [menu_msg]}
        _append_message(conversation_id, "assistant", "Pick model")
        return out

    if lowered.startswith("imagen model "):
        sel = cleaned[len("imagen model ") :].strip()
        if not sel:
            out = {"reply_type": "text", "text": "Usage: imagen model <sdxl|model_name>"}
            _append_message(conversation_id, "assistant", out["text"])
            return out
        # Persist selection for this conversation; applied on approve.
        _merge_imagen_pending(updates={"imagenModel": sel})
        out = {"reply_type": "text", "text": f"OK. Model set to {sel}. Send: imagen run"}
        _append_message(conversation_id, "assistant", out["text"])
        return out

    if lowered in ("imagen sum", "imagen summary"):
        pending = _imagen_pending_by_conversation.get(cid) or {}
        prompt = str(pending.get("prompt") or "").strip()
        if not pending:
            out = {"reply_type": "text", "text": "No pending imagen request. Send: imagen <prompt>"}
            _append_message(conversation_id, "assistant", out["text"])
            return out
        lines = []
        if prompt:
            lines.append(f"prompt: {prompt}")
        neg = str(pending.get("negativePrompt") or "").strip()
        if neg:
            lines.append(f"neg: {neg}")
        model_sel = str(pending.get("imagenModel") or "").strip()
        if model_sel:
            lines.append(f"model: {model_sel}")
        steps = pending.get("numInferenceSteps")
        if steps is not None:
            lines.append(f"steps: {steps}")
        seed = pending.get("seed")
        if seed is not None:
            lines.append(f"seed: {seed}")
        w = pending.get("width")
        h = pending.get("height")
        if w and h:
            lines.append(f"size: {w}x{h}")
        ref_b64 = str(pending.get("referenceImageBase64") or "").strip()
        ref_mime = str(pending.get("referenceImageMimeType") or "").strip()
        ref_dims = pending.get("referenceImageDimensions")
        if ref_b64:
            lines.append("ref_image: set")
            if ref_mime:
                lines.append(f"ref_mime: {ref_mime}")
            if isinstance(ref_dims, (list, tuple)) and len(ref_dims) == 2:
                try:
                    lines.append(f"ref_size: {int(ref_dims[0])}x{int(ref_dims[1])}")
                except Exception:
                    pass
        else:
            lines.append("ref_image: (none)")
        out = {"reply_type": "text", "text": "\n".join(lines)[:2000]}
        _append_message(conversation_id, "assistant", out["text"])
        return out

    if lowered == "imagen" or lowered.startswith("imagen "):
        cmd = lowered
        rest = ""
        if cmd != "imagen":
            rest = cleaned[len("imagen ") :].strip()
            cmd = "imagen " + rest.lower()

        if cmd in ("imagen",):
            return _menu_default()

        if cmd in ("imagen apply", "imagen apply extracted"):
            if not _imagen_expect_apply_extracted_by_conversation.get(cid):
                out = {"reply_type": "text", "text": "Nothing to apply."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            diff = _imagen_extracted_diff_by_conversation.get(cid) or {}
            updates: Dict[str, Any] = {}
            for k, v in diff.items():
                if isinstance(v, dict) and "to" in v:
                    updates[k] = v.get("to")
            _merge_imagen_pending(updates=updates)
            _imagen_expect_apply_extracted_by_conversation[cid] = False
            _imagen_extracted_diff_by_conversation.pop(cid, None)
            out = {"reply_type": "text", "text": "OK. Applied extracted parameters."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen discard", "imagen discard extracted"):
            _imagen_expect_apply_extracted_by_conversation[cid] = False
            _imagen_extracted_diff_by_conversation.pop(cid, None)
            out = {"reply_type": "text", "text": "OK. Discarded extracted parameters."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen show",):
            pending = _imagen_pending_by_conversation.get(cid) or {}
            pending = dict(pending) if isinstance(pending, dict) else {}
            safe = dict(pending)
            if str(safe.get("referenceImageBase64") or "").strip():
                safe["referenceImageBase64"] = "(set)"
            out = {"reply_type": "text", "text": str(safe)[:2000]}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd.startswith("imagen reset"):
            scope = cleaned[len("imagen") :].strip()[len("reset") :].strip().lower()
            if not scope:
                menu_msg = _line_menu_message(
                    "Reset what?",
                    [
                        ("All", "imagen reset all"),
                        ("Prompt", "imagen reset prompt"),
                        ("Neg", "imagen reset neg"),
                        ("Ref", "imagen reset ref"),
                        ("Params", "imagen reset params"),
                    ],
                )
                out = {"reply_type": "line_messages", "messages": [menu_msg]}
                _append_message(conversation_id, "assistant", "Reset what")
                return out
            scope = scope.split()[0]
            pending = _imagen_pending_by_conversation.get(cid) or {}
            pending = dict(pending) if isinstance(pending, dict) else {}
            if scope in ("all", "clear"):
                _imagen_pending_by_conversation.pop(cid, None)
                _imagen_expect_refine_by_conversation[cid] = False
                _imagen_expect_ref_image_by_conversation[cid] = False
                _imagen_expect_apply_extracted_by_conversation[cid] = False
                _imagen_extracted_diff_by_conversation.pop(cid, None)
                _imagen_expect_prompt_by_conversation[cid] = False
                _imagen_expect_neg_by_conversation[cid] = False
                out = {"reply_type": "text", "text": "Cleared imagen session."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            if scope == "prompt":
                pending.pop("prompt", None)
            elif scope in ("neg", "negative"):
                pending.pop("negativePrompt", None)
            elif scope in ("ref", "reference"):
                pending.pop("referenceImageBase64", None)
                pending.pop("referenceImageMimeType", None)
                pending.pop("referenceImageDimensions", None)
            elif scope == "params":
                for k in ("numInferenceSteps", "seed", "width", "height", "guidanceScale", "strength", "imagenModel"):
                    pending.pop(k, None)
            else:
                out = {"reply_type": "text", "text": "Usage: imagen reset <all|prompt|neg|ref|params>"}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            pending["updatedAt"] = _utc_ts()
            _imagen_pending_by_conversation[cid] = pending
            out = {"reply_type": "text", "text": f"OK. Reset {scope}."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd.startswith("imagen preset"):
            tail = cleaned[len("imagen") :].strip()[len("preset") :].strip()
            action = (tail.split()[0].lower() if tail else "")
            name = " ".join(tail.split()[1:]).strip() if len(tail.split()) > 1 else ""
            if not action:
                menu_msg = _line_menu_message(
                    "Preset:",
                    [("List", "imagen preset list"), ("Save", "imagen preset save mypreset"), ("Load", "imagen preset load mypreset")],
                )
                out = {"reply_type": "line_messages", "messages": [menu_msg]}
                _append_message(conversation_id, "assistant", "Preset")
                return out
            uid = str(user_id or "").strip() or cid
            store = _imagen_presets_by_user.get(uid)
            if store is None:
                store = {}
                _imagen_presets_by_user[uid] = store
            if action == "list":
                names = sorted([k for k in store.keys() if str(k).strip()])
                if not names:
                    out = {"reply_type": "text", "text": "No presets saved."}
                    _append_message(conversation_id, "assistant", out["text"])
                    return out
                menu_msg = _line_menu_message("Presets:", [(n, f"imagen preset load {n}") for n in names[:12]])
                out = {"reply_type": "line_messages", "messages": [menu_msg]}
                _append_message(conversation_id, "assistant", "Presets")
                return out
            if action == "save":
                if not name:
                    out = {"reply_type": "text", "text": "Usage: imagen preset save <name>"}
                    _append_message(conversation_id, "assistant", out["text"])
                    return out
                pending = _imagen_pending_by_conversation.get(cid) or {}
                pending = dict(pending) if isinstance(pending, dict) else {}
                preset = dict(pending)
                preset.pop("referenceImageBase64", None)
                preset.pop("referenceImageMimeType", None)
                preset.pop("referenceImageDimensions", None)
                store[name] = preset
                out = {"reply_type": "text", "text": f"OK. Preset saved: {name}"}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            if action == "load":
                if not name:
                    out = {"reply_type": "text", "text": "Usage: imagen preset load <name>"}
                    _append_message(conversation_id, "assistant", out["text"])
                    return out
                preset = store.get(name)
                if not isinstance(preset, dict):
                    out = {"reply_type": "text", "text": "Preset not found."}
                    _append_message(conversation_id, "assistant", out["text"])
                    return out
                _merge_imagen_pending(updates=preset)
                out = {"reply_type": "text", "text": f"OK. Preset loaded: {name}"}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            out = {"reply_type": "text", "text": "Usage: imagen preset <list|save|load> ..."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen jobs",):
            jobs = list(_imagen_jobs_by_conversation.get(cid) or [])
            if not jobs:
                out = {"reply_type": "text", "text": "No jobs yet."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            jobs = jobs[-10:]
            for j in jobs:
                await _refresh_job_status(j)
            lines: List[str] = []
            items: List[Tuple[str, str]] = []
            for j in reversed(jobs):
                jid = str(j.get("job_id") or "").strip() or "(unknown)"
                st = str(j.get("status") or "").strip() or "unknown"
                step = j.get("step")
                steps = j.get("steps")
                prog = ""
                if step is not None and steps is not None:
                    prog = f" {int(step)}/{int(steps)}"
                lines.append(f"{jid}  {st}{prog}")
                items.append((jid[:12], f"imagen job {jid}"))
            menu_msg = _line_menu_message("Jobs:\n" + "\n".join(lines), items)
            out = {"reply_type": "line_messages", "messages": [menu_msg]}
            _append_message(conversation_id, "assistant", "Jobs")
            return out

        if cmd.startswith("imagen job "):
            job_id = cleaned[len("imagen job ") :].strip()
            if not job_id:
                out = {"reply_type": "text", "text": "Usage: imagen job <job_id>"}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            jobs = list(_imagen_jobs_by_conversation.get(cid) or [])
            found = None
            for j in jobs:
                if str(j.get("job_id") or "").strip() == job_id:
                    found = j
                    break
            if found is None:
                out = {"reply_type": "text", "text": "Job not found. Try: imagen jobs"}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            await _refresh_job_status(found)
            await _refresh_job_preview(found)
            await _refresh_job_result(found)
            out_txt = _format_jobs_table([found])
            menu_msg = _line_menu_message(out_txt, [("Jobs", "imagen jobs"), ("Remove", f"imagen cancel {job_id}"), ("Help", "imagen help")])
            out = {"reply_type": "line_messages", "messages": [menu_msg]}
            _append_message(conversation_id, "assistant", "Job")
            return out

        if cmd.startswith("imagen seed"):
            seed_raw = cleaned[len("imagen") :].strip()[len("seed") :].strip()
            if not seed_raw:
                menu_msg = _line_menu_message(
                    "Pick seed:",
                    [("Random", "imagen seed random"), ("0", "imagen seed 0"), ("42", "imagen seed 42"), ("123", "imagen seed 123"), ("Clear", "imagen seed clear")],
                )
                out = {"reply_type": "line_messages", "messages": [menu_msg]}
                _append_message(conversation_id, "assistant", "Pick seed")
                return out
            if seed_raw.lower() in ("random", "rand"):
                pending = _imagen_pending_by_conversation.get(cid) or {}
                pending = dict(pending) if isinstance(pending, dict) else {}
                pending.pop("seed", None)
                pending["updatedAt"] = _utc_ts()
                _imagen_pending_by_conversation[cid] = pending
                out = {"reply_type": "text", "text": "OK. Seed set to random."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            if seed_raw.lower() in ("clear", "none"):
                pending = _imagen_pending_by_conversation.get(cid) or {}
                pending = dict(pending) if isinstance(pending, dict) else {}
                pending.pop("seed", None)
                pending["updatedAt"] = _utc_ts()
                _imagen_pending_by_conversation[cid] = pending
                out = {"reply_type": "text", "text": "OK. Seed cleared."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            try:
                seed_val = int(seed_raw)
            except Exception:
                seed_val = -1
            if seed_val < 0:
                out = {"reply_type": "text", "text": "Usage: imagen seed <nonnegative_int|random|clear>"}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            pending = _imagen_pending_by_conversation.get(cid) or {}
            pending = dict(pending) if isinstance(pending, dict) else {}
            pending["seed"] = seed_val
            pending["updatedAt"] = _utc_ts()
            _imagen_pending_by_conversation[cid] = pending
            out = {"reply_type": "text", "text": f"OK. Seed set to {seed_val}."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd.startswith("imagen prompt"):
            prompt_raw = cleaned[len("imagen") :].strip()[len("prompt") :].strip()
            if not prompt_raw:
                _imagen_expect_prompt_by_conversation[cid] = True
                _imagen_expect_neg_by_conversation[cid] = False
                out = {"reply_type": "text", "text": "OK. Send your prompt now."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            prompt_clean, extracted = _parse_imagen_inline_params(prompt_raw)
            before = _imagen_pending_by_conversation.get(cid) or {}
            before = dict(before) if isinstance(before, dict) else {}
            _merge_imagen_pending(updates={"prompt": prompt_clean})
            if extracted:
                diff = _diff_pending(before, extracted)
                if diff:
                    _imagen_expect_apply_extracted_by_conversation[cid] = True
                    _imagen_extracted_diff_by_conversation[cid] = diff
                    lines = ["Extracted params:"]
                    for k, d in diff.items():
                        lines.append(f"- {k}: {d.get('from')} -> {d.get('to')}")
                    menu_msg = _line_menu_message("\n".join(lines), [("Apply", "imagen apply"), ("Discard", "imagen discard"), ("Run", "imagen run")])
                    out = {"reply_type": "line_messages", "messages": [menu_msg]}
                    _append_message(conversation_id, "assistant", "Extracted params")
                    return out
            out = {"reply_type": "text", "text": "OK. Prompt set. Send: imagen run"}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd.startswith("imagen neg") or cmd.startswith("imagen negative"):
            key = "neg" if cmd.startswith("imagen neg") else "negative"
            neg_raw = cleaned[len("imagen") :].strip()[len(key) :].strip()
            if not neg_raw:
                _imagen_expect_neg_by_conversation[cid] = True
                _imagen_expect_prompt_by_conversation[cid] = False
                out = {"reply_type": "text", "text": "OK. Send your negative prompt now."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            _merge_imagen_pending(updates={"negativePrompt": neg_raw})
            out = {"reply_type": "text", "text": "OK. Negative prompt set."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd.startswith("imagen run "):
            prompt_override = cleaned[len("imagen run ") :].strip()
            if prompt_override:
                prompt_clean, extracted = _parse_imagen_inline_params(prompt_override)
                before = _imagen_pending_by_conversation.get(cid) or {}
                before = dict(before) if isinstance(before, dict) else {}
                _merge_imagen_pending(updates={"prompt": prompt_clean})
                if extracted:
                    diff = _diff_pending(before, extracted)
                    if diff:
                        _imagen_expect_apply_extracted_by_conversation[cid] = True
                        _imagen_extracted_diff_by_conversation[cid] = diff
            cmd = "imagen run"

        if cmd.startswith("imagen steps"):
            steps_raw = cleaned[len("imagen ") :].strip()[len("steps") :].strip()
            if not steps_raw:
                items = []
                for n in (5, 10, 20, 30, 40, 50):
                    items.append({"type": "action", "action": {"type": "message", "label": str(n), "text": f"imagen steps {n}"}})
                menu_msg = {"type": "text", "text": "Pick steps:", "quickReply": {"items": items}}
                out = {"reply_type": "line_messages", "messages": [menu_msg]}
                _append_message(conversation_id, "assistant", "Pick steps")
                return out
            try:
                steps = int(str(steps_raw or "").strip())
            except Exception:
                steps = 0
            if steps <= 0:
                out = {"reply_type": "text", "text": "Usage: imagen steps <N> (N must be a positive integer)"}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            pending = _imagen_pending_by_conversation.get(cid) or {}
            pending = dict(pending) if isinstance(pending, dict) else {}
            pending["numInferenceSteps"] = steps
            pending["updatedAt"] = _utc_ts()
            _imagen_pending_by_conversation[cid] = pending
            out = {"reply_type": "text", "text": f"OK. Steps set to {steps}. Click: imagen approve"}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd.startswith("imagen resolution"):
            res_raw = cleaned[len("imagen ") :].strip()[len("resolution") :].strip()
            if not res_raw:
                items = []
                for label, w, h in (("256*256", 256, 256), ("512*512", 512, 512), ("1920*1080", 1920, 1080)):
                    items.append(
                        {
                            "type": "action",
                            "action": {"type": "message", "label": label, "text": f"imagen resolution {w}x{h}"},
                        }
                    )
                menu_msg = {"type": "text", "text": "Pick resolution:", "quickReply": {"items": items}}
                out = {"reply_type": "line_messages", "messages": [menu_msg]}
                _append_message(conversation_id, "assistant", "Pick resolution")
                return out
            normalized = res_raw.lower().replace("*", "x").replace("×", "x")
            parts = [p.strip() for p in normalized.split("x", 1)]
            try:
                w = int(parts[0])
                h = int(parts[1])
            except Exception:
                w = 0
                h = 0
            if w <= 0 or h <= 0:
                out = {"reply_type": "text", "text": "Usage: imagen resolution <W>x<H> (example: imagen resolution 512x512)"}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            pending = _imagen_pending_by_conversation.get(cid) or {}
            pending = dict(pending) if isinstance(pending, dict) else {}
            pending["width"] = w
            pending["height"] = h
            pending["updatedAt"] = _utc_ts()
            _imagen_pending_by_conversation[cid] = pending
            out = {"reply_type": "text", "text": f"OK. Resolution set to {w}x{h}. Click: imagen approve"}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen help",):
            msg = (
                "Imagen menu commands:\n"
                "- imagen: show status/menu\n"
                "- imagen prompt <text>: set prompt (supports steps=, seed=, model=, neg=)\n"
                "- imagen neg <text>: set negative prompt\n"
                "- imagen ref: request reference image\n"
                "- imagen ref clear: clear reference image\n"
                "- imagen steps <n>: set inference steps\n"
                "- imagen seed <n|random|clear>: set seed\n"
                "- imagen model / imagen models: pick a model\n"
                "- imagen run (alias: imagen approve): start generation\n"
                "- imagen sum: show pending request summary\n"
                "- imagen jobs: list jobs\n"
                "- imagen job <id>: job detail\n"
                "- imagen preset <list|save|load> ...\n"
                "- imagen reset <all|prompt|neg|ref|params>"
            )
            out = {"reply_type": "text", "text": msg}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd.startswith("imagen cancel"):
            tail = cleaned[len("imagen") :].strip()[len("cancel") :].strip()
            if tail:
                # We can't reliably cancel compute on the backend; just stop tracking.
                job_id = tail.split()[0]
                lst = list(_imagen_jobs_by_conversation.get(cid) or [])
                kept = [j for j in lst if str(j.get("job_id") or "").strip() != job_id]
                _imagen_jobs_by_conversation[cid] = kept
                out = {"reply_type": "text", "text": "Removed job from list (backend cancellation not supported)."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            _imagen_pending_by_conversation.pop(cid, None)
            _imagen_expect_refine_by_conversation[cid] = False
            _imagen_expect_prompt_by_conversation[cid] = False
            _imagen_expect_neg_by_conversation[cid] = False
            out = {"reply_type": "text", "text": "Canceled."}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen clear",):
            _imagen_pending_by_conversation.pop(cid, None)
            _imagen_expect_refine_by_conversation[cid] = False
            _imagen_jobs_by_conversation.pop(cid, None)
            _imagen_last_job_by_conversation.pop(cid, None)
            _imagen_expect_apply_extracted_by_conversation[cid] = False
            _imagen_extracted_diff_by_conversation.pop(cid, None)
            _imagen_expect_prompt_by_conversation[cid] = False
            _imagen_expect_neg_by_conversation[cid] = False
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
                await _refresh_job_result(j)
            out = {"reply_type": "text", "text": _format_jobs_table(jobs)}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        if cmd in ("imagen approve", "imagen run"):
            pending = _imagen_pending_by_conversation.get(cid) or {}
            prompt = str(pending.get("prompt") or "").strip()
            if not prompt:
                out = {"reply_type": "text", "text": "No pending prompt. Send: imagen <prompt>"}
                _append_message(conversation_id, "assistant", out["text"])
                return out

            if _imagen_expect_apply_extracted_by_conversation.get(cid):
                diff = _imagen_extracted_diff_by_conversation.get(cid) or {}
                if diff:
                    menu_msg = _line_menu_message(
                        "You have extracted params not applied yet. Apply first?",
                        [("Apply", "imagen apply"), ("Discard", "imagen discard"), ("Run", "imagen run")],
                    )
                    out = {"reply_type": "line_messages", "messages": [menu_msg]}
                    _append_message(conversation_id, "assistant", "Apply extracted params")
                    return out

            # Apply selected model (global to mcp-cuda) before starting generation.
            model_sel = str(pending.get("imagenModel") or "").strip().lower()
            if model_sel:
                if model_sel == "sdxl":
                    cuda_tool = "mcp-cuda_1mcp_imagen_model_clear"
                    allowed = _allowed_tools_for_user(user_id)
                    if allowed and cuda_tool not in allowed:
                        out = {"reply_type": "text", "text": "Model selection tool not allowed."}
                        _append_message(conversation_id, "assistant", out["text"])
                        return out
                    try:
                        await _invoke_1mcp(cuda_tool, {}, conversation_id, user_id)
                    except Exception as exc:
                        out = {"reply_type": "text", "text": f"Failed to set model: {exc}"}
                        _append_message(conversation_id, "assistant", out["text"][:2000])
                        return out
                else:
                    cuda_tool = "mcp-cuda_1mcp_imagen_model_set"
                    allowed = _allowed_tools_for_user(user_id)
                    if allowed and cuda_tool not in allowed:
                        out = {"reply_type": "text", "text": "Model selection tool not allowed."}
                        _append_message(conversation_id, "assistant", out["text"])
                        return out
                    try:
                        await _invoke_1mcp(cuda_tool, {"model": str(pending.get("imagenModel") or "").strip()}, conversation_id, user_id)
                    except Exception as exc:
                        out = {"reply_type": "text", "text": f"Failed to set model: {exc}"}
                        _append_message(conversation_id, "assistant", out["text"][:2000])
                        return out

            tool_name = "mcp-imagen-light_1mcp_imagen_generate"
            allowed = _allowed_tools_for_user(user_id)
            if allowed and tool_name not in allowed:
                out = {"reply_type": "text", "text": "Image tool not allowed."}
                _append_message(conversation_id, "assistant", out["text"])
                return out
            args: Dict[str, Any] = {"prompt": prompt}
            neg = str(pending.get("negativePrompt") or "").strip()
            if neg:
                args["negativePrompt"] = neg
            try:
                pending_w = int(pending.get("width") or 0)
                pending_h = int(pending.get("height") or 0)
            except Exception:
                pending_w = 0
                pending_h = 0
            if pending.get("width") and pending.get("height"):
                args["width"] = int(pending.get("width"))
                args["height"] = int(pending.get("height"))
            else:
                args["width"] = int(MCP_ASSISTANT_IMAGEN_WIDTH)
                args["height"] = int(MCP_ASSISTANT_IMAGEN_HEIGHT)
            try:
                steps = int(pending.get("numInferenceSteps") or 50)
            except Exception:
                steps = 50
            if steps > 0:
                args["numInferenceSteps"] = steps

            if pending.get("seed") is not None:
                try:
                    args["seed"] = int(pending.get("seed"))
                except Exception:
                    pass

            ref_b64 = str(pending.get("referenceImageBase64") or "").strip()
            if ref_b64:
                args["referenceImageBase64"] = ref_b64
                ref_dims = pending.get("referenceImageDimensions")
                if isinstance(ref_dims, (list, tuple)) and len(ref_dims) == 2:
                    try:
                        args["referenceImageDimensions"] = [int(ref_dims[0]), int(ref_dims[1])]
                    except Exception:
                        pass

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
            prompt_clean, extracted = _parse_imagen_inline_params(rest)
            before = _imagen_pending_by_conversation.get(cid) or {}
            before = dict(before) if isinstance(before, dict) else {}
            _merge_imagen_pending(updates={"prompt": prompt_clean})
            if extracted:
                diff = _diff_pending(before, extracted)
                if diff:
                    _imagen_expect_apply_extracted_by_conversation[cid] = True
                    _imagen_extracted_diff_by_conversation[cid] = diff
                    lines = ["Extracted params:"]
                    for k, d in diff.items():
                        lines.append(f"- {k}: {d.get('from')} -> {d.get('to')}")
                    menu_msg = _line_menu_message(
                        "\n".join(lines),
                        [("Apply", "imagen apply"), ("Discard", "imagen discard"), ("Run", "imagen run"), ("Menu", "imagen")],
                    )
                    out = {"reply_type": "line_messages", "messages": [menu_msg]}
                    _append_message(conversation_id, "assistant", "Extracted params")
                    return out
            out = {"reply_type": "text", "text": "Ready. Send: imagen run"}
            _append_message(conversation_id, "assistant", out["text"])
            return out

        return _menu_default()
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
        _merge_imagen_pending(updates={"prompt": cleaned})
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
    line_message = (body or {}).get("line_message") or {}
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
        if isinstance(line_message, dict) and str(line_message.get("type") or "").strip() == "image":
            reply = _handle_line_image_message(conversation_id=conversation_id, user_id=user_id, line_message=line_message)
        else:
            reply = await _agent_reply(text=user_text, conversation_id=conversation_id, user_id=user_id)
    except Exception as exc:
        logger.warning("line_reply_failed: %s", str(exc))
        reply = {"reply_type": "text", "text": "Sorry, I had an error while processing that."}

    if reply.get("reply_type") == "line_messages" and isinstance(reply.get("messages"), list):
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "messages": reply.get("messages"),
        }

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


def _handle_line_image_message(*, conversation_id: str, user_id: str, line_message: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(conversation_id or "").strip() or "__default__"
    if not _imagen_expect_ref_image_by_conversation.get(cid):
        out = {"reply_type": "text", "text": "Send: imagen ref (then send an image)."}
        _append_message(conversation_id, "assistant", out["text"])
        return out

    b64 = str((line_message or {}).get("imageBase64") or "").strip()
    mime = str((line_message or {}).get("mimeType") or "").strip()
    if not b64:
        out = {"reply_type": "text", "text": "I couldn't read the image. Please try sending it again."}
        _append_message(conversation_id, "assistant", out["text"])
        return out

    b64_out = b64
    mime_out = mime
    dims_out: List[int] = []
    try:
        raw_in = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw_in))
        img = img.convert("RGB")
        w0, h0 = int(img.width), int(img.height)
        if w0 > 0 and h0 > 0:
            max_side = 512
            scale = min(1.0, float(max_side) / float(max(w0, h0)))
            w1 = max(1, int(round(w0 * scale)))
            h1 = max(1, int(round(h0 * scale)))
            if (w1, h1) != (w0, h0):
                img = img.resize((w1, h1), Image.LANCZOS)
            dims_out = [int(img.width), int(img.height)]

        buf = io.BytesIO()
        quality = 75
        while True:
            buf.seek(0)
            buf.truncate(0)
            img.save(buf, format="JPEG", quality=int(quality), optimize=True)
            b64_candidate = base64.b64encode(buf.getvalue()).decode("utf-8")
            if len(b64_candidate) <= 80_000 or quality <= 35:
                b64_out = b64_candidate
                mime_out = "image/jpeg"
                break
            quality = int(quality) - 10
    except Exception:
        b64_out = b64
        mime_out = mime
        dims_out = []

    pending = _imagen_pending_by_conversation.get(cid) or {}
    pending = dict(pending) if isinstance(pending, dict) else {}
    pending["referenceImageBase64"] = b64_out
    if mime_out:
        pending["referenceImageMimeType"] = mime_out
    if dims_out:
        pending["referenceImageDimensions"] = dims_out
    else:
        try:
            raw = base64.b64decode(b64_out)
            img2 = Image.open(io.BytesIO(raw))
            pending["referenceImageDimensions"] = [int(img2.width), int(img2.height)]
        except Exception:
            pass

    pending["updatedAt"] = _utc_ts()
    _imagen_pending_by_conversation[cid] = pending
    _imagen_expect_ref_image_by_conversation[cid] = False

    out = {"reply_type": "text", "text": "OK. Reference image set. Click: imagen approve"}
    _append_message(conversation_id, "assistant", out["text"])
    return out
