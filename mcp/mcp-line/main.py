import asyncio
import base64
import hmac
import hashlib
import logging
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-line")
logger.setLevel(logging.INFO)

LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET") or "").strip()
LINE_CHANNEL_ACCESS_TOKEN = (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()

LINE_USE_GLAMA = (os.getenv("LINE_USE_GLAMA") or "").strip().lower() in ("1", "true", "yes", "y", "on")
GLAMA_MCP_URL = (os.getenv("GLAMA_MCP_URL") or "").strip()
MCP_GLAMA_URL = (os.getenv("MCP_GLAMA_URL") or "http://host.docker.internal:7441").strip()
GLAMA_MODEL = (os.getenv("GLAMA_MODEL") or "").strip()
GLAMA_SYSTEM_PROMPT = (os.getenv("GLAMA_SYSTEM_PROMPT") or "").strip()

MCP_ASSISTANT_URL = (os.getenv("MCP_ASSISTANT_URL") or "").strip().rstrip("/")
MCP_ASSISTANT_CONTROL_TOKEN = (os.getenv("MCP_ASSISTANT_CONTROL_TOKEN") or "").strip()

ONE_MCP_URL = (os.getenv("ONE_MCP_URL") or "").strip()
MCP_LINE_ALLOWED_TOOLS = (os.getenv("MCP_LINE_ALLOWED_TOOLS") or "").strip()
MCP_LINE_AGENT_ENABLED = (os.getenv("MCP_LINE_AGENT_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")

ONE_MCP_BASIC_AUTH = (os.getenv("ONE_MCP_BASIC_AUTH") or "").strip()
ONE_MCP_USERNAME = (os.getenv("ONE_MCP_USERNAME") or "").strip()
ONE_MCP_PASSWORD = (os.getenv("ONE_MCP_PASSWORD") or "").strip()


def _utc_ts() -> int:
    return int(time.time())


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _get_db_path() -> str:
    return os.getenv("MCP_LINE_DB_PATH", "/data/sqlite/mcp-line.sqlite")


def _get_control_token() -> str:
    return str(os.getenv("MCP_LINE_CONTROL_TOKEN", "") or "").strip()


def _get_control_token_from_request(request: Request) -> str:
    try:
        token = str(request.query_params.get("token") or "").strip()
    except Exception:
        token = ""
    if token:
        return token
    header = str(request.headers.get("x-control-token") or "").strip()
    return header


def _require_control_auth(request: Request) -> None:
    required = _get_control_token()
    if not required:
        return
    provided = _get_control_token_from_request(request)
    if not provided or provided != required:
        raise HTTPException(status_code=401, detail="control_unauthorized")


def _line_auth_headers(content_type: Optional[str] = None) -> Dict[str, str]:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="line_channel_access_token_not_configured")
    headers: Dict[str, str] = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


async def _line_api_json(method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"https://api.line.me{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.request(method.upper(), url, headers=_line_auth_headers("application/json"), json=json_body)
    if r.status_code >= 400:
        body = (r.text or "")[:800]
        raise HTTPException(status_code=502, detail=f"line_api_{r.status_code}: {body}")
    if r.headers.get("content-type", "").lower().startswith("application/json"):
        return r.json()  # type: ignore[no-any-return]
    return {}


async def _line_api_bytes(method: str, path: str, *, body: bytes, content_type: str) -> Dict[str, Any]:
    url = f"https://api.line.me{path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.request(method.upper(), url, headers=_line_auth_headers(content_type), content=body)
    if r.status_code >= 400:
        body_txt = (r.text or "")[:800]
        raise HTTPException(status_code=502, detail=f"line_api_{r.status_code}: {body_txt}")
    if r.headers.get("content-type", "").lower().startswith("application/json"):
        return r.json()  # type: ignore[no-any-return]
    return {}


@app.get("/control/line/richmenu/list")
async def control_line_richmenu_list(request: Request) -> Dict[str, Any]:
    _require_control_auth(request)
    return await _line_api_json("GET", "/v2/bot/richmenu/list")


@app.post("/control/line/richmenu/create")
async def control_line_richmenu_create(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    _require_control_auth(request)
    data = await _line_api_json("POST", "/v2/bot/richmenu", json_body=payload)
    rich_menu_id = str((data or {}).get("richMenuId") or "").strip()
    return {"richMenuId": rich_menu_id, "raw": data}


@app.post("/control/line/richmenu/{rich_menu_id}/content")
async def control_line_richmenu_upload_content(request: Request, rich_menu_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _require_control_auth(request)
    b64 = str((payload or {}).get("imageBase64") or "").strip()
    if not b64:
        raise HTTPException(status_code=400, detail="imageBase64_required")
    mime = str((payload or {}).get("mimeType") or "image/png").strip() or "image/png"
    try:
        raw = base64.b64decode(b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_base64: {exc}")
    await _line_api_bytes("POST", f"/v2/bot/richmenu/{rich_menu_id}/content", body=raw, content_type=mime)
    return {"ok": True, "richMenuId": rich_menu_id}


@app.post("/control/line/richmenu/default")
async def control_line_richmenu_set_default(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    _require_control_auth(request)
    rich_menu_id = str((payload or {}).get("richMenuId") or "").strip()
    if not rich_menu_id:
        raise HTTPException(status_code=400, detail="richMenuId_required")
    await _line_api_json("POST", f"/v2/bot/user/all/richmenu/{rich_menu_id}")
    return {"ok": True, "richMenuId": rich_menu_id}


@app.post("/control/line/richmenu/default/cancel")
async def control_line_richmenu_cancel_default(request: Request) -> Dict[str, Any]:
    _require_control_auth(request)
    await _line_api_json("DELETE", "/v2/bot/user/all/richmenu")
    return {"ok": True}


@app.delete("/control/line/richmenu/{rich_menu_id}")
async def control_line_richmenu_delete(request: Request, rich_menu_id: str) -> Dict[str, Any]:
    _require_control_auth(request)
    await _line_api_json("DELETE", f"/v2/bot/richmenu/{rich_menu_id}")
    return {"ok": True, "richMenuId": rich_menu_id}


_conn: Optional[sqlite3.Connection] = None


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS people ("
        "person_id TEXT PRIMARY KEY,"
        "full_name TEXT NOT NULL,"
        "created_at INTEGER NOT NULL,"
        "updated_at INTEGER NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS line_identities ("
        "line_user_id TEXT PRIMARY KEY,"
        "person_id TEXT NULL,"
        "created_at INTEGER NOT NULL,"
        "last_seen_at INTEGER NOT NULL,"
        "FOREIGN KEY(person_id) REFERENCES people(person_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS line_conversations ("
        "conversation_id TEXT PRIMARY KEY,"
        "source_type TEXT NOT NULL,"
        "source_id TEXT NOT NULL,"
        "created_at INTEGER NOT NULL,"
        "updated_at INTEGER NOT NULL,"
        "UNIQUE(source_type, source_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS line_messages ("
        "message_id TEXT PRIMARY KEY,"
        "conversation_id TEXT NOT NULL,"
        "line_user_id TEXT NULL,"
        "person_id TEXT NULL,"
        "event_type TEXT NOT NULL,"
        "message_type TEXT NULL,"
        "text TEXT NULL,"
        "line_event_ts INTEGER NULL,"
        "received_at INTEGER NOT NULL,"
        "raw_event_json TEXT NOT NULL,"
        "FOREIGN KEY(conversation_id) REFERENCES line_conversations(conversation_id),"
        "FOREIGN KEY(person_id) REFERENCES people(person_id)"
        ")"
    )
    conn.commit()


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        raise RuntimeError("db_not_initialized")
    return _conn


@app.on_event("startup")
def _startup() -> None:
    global _conn
    path = _get_db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    _conn = conn


def _conversation_source(evt: Dict[str, Any]) -> Optional[Dict[str, str]]:
    src = evt.get("source") or {}
    if not isinstance(src, dict):
        return None
    src_type = str(src.get("type") or "").strip()
    if src_type == "user":
        src_id = str(src.get("userId") or "").strip()
        return {"type": "user", "id": src_id} if src_id else None
    if src_type == "group":
        src_id = str(src.get("groupId") or "").strip()
        return {"type": "group", "id": src_id} if src_id else None
    if src_type == "room":
        src_id = str(src.get("roomId") or "").strip()
        return {"type": "room", "id": src_id} if src_id else None
    return None


def _get_or_create_conversation(source_type: str, source_id: str) -> str:
    conn = _get_conn()
    row = conn.execute(
        "SELECT conversation_id FROM line_conversations WHERE source_type=? AND source_id=?",
        (source_type, source_id),
    ).fetchone()
    if row is not None:
        conversation_id = str(row["conversation_id"])
        conn.execute(
            "UPDATE line_conversations SET updated_at=? WHERE conversation_id=?",
            (_utc_ts(), conversation_id),
        )
        conn.commit()
        return conversation_id

    conversation_id = str(uuid.uuid4())
    now = _utc_ts()
    conn.execute(
        "INSERT INTO line_conversations (conversation_id, source_type, source_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (conversation_id, source_type, source_id, now, now),
    )
    conn.commit()
    return conversation_id


def _upsert_line_identity(line_user_id: str) -> None:
    cleaned = str(line_user_id or "").strip()
    if not cleaned:
        return
    conn = _get_conn()
    now = _utc_ts()
    conn.execute(
        "INSERT INTO line_identities (line_user_id, person_id, created_at, last_seen_at) VALUES (?, NULL, ?, ?) "
        "ON CONFLICT(line_user_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
        (cleaned, now, now),
    )
    conn.commit()


def _person_id_for_line_user(line_user_id: str) -> Optional[str]:
    cleaned = str(line_user_id or "").strip()
    if not cleaned:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT person_id FROM line_identities WHERE line_user_id=?",
        (cleaned,),
    ).fetchone()
    if row is None:
        return None
    val = row["person_id"]
    return str(val) if val else None


def _insert_line_event_message(
    *,
    conversation_id: str,
    evt: Dict[str, Any],
    line_user_id: Optional[str],
    person_id: Optional[str],
    event_type: str,
    message_type: Optional[str],
    text: Optional[str],
) -> str:
    conn = _get_conn()
    message_id = str(uuid.uuid4())
    received_at = _utc_ts()
    line_event_ts = evt.get("timestamp")
    try:
        line_event_ts_int = int(line_event_ts) if line_event_ts is not None else None
    except Exception:
        line_event_ts_int = None
    conn.execute(
        "INSERT INTO line_messages (message_id, conversation_id, line_user_id, person_id, event_type, message_type, text, line_event_ts, received_at, raw_event_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            message_id,
            conversation_id,
            str(line_user_id).strip() if line_user_id else None,
            str(person_id).strip() if person_id else None,
            str(event_type),
            str(message_type).strip() if message_type else None,
            str(text) if text is not None else None,
            line_event_ts_int,
            received_at,
            _json_dumps(evt),
        ),
    )
    conn.commit()
    return message_id


def _verify_line_signature(raw_body: bytes, signature_b64: Optional[str]) -> bool:
    if not LINE_CHANNEL_SECRET:
        return False
    if not signature_b64:
        return False

    mac = hmac.new(LINE_CHANNEL_SECRET.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature_b64)


async def _reply_message(reply_token: str, text: str) -> None:
    await _reply_messages(reply_token=reply_token, messages=[{"type": "text", "text": text}])


async def _reply_messages(reply_token: str, messages: List[Dict[str, Any]]) -> None:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    if not reply_token:
        return

    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "replyToken": reply_token,
        "messages": messages,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            detail = (resp.text or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            logger.warning("LINE reply failed: status=%s body=%s", resp.status_code, detail)
            raise RuntimeError(f"line_reply_failed_{resp.status_code}:{detail}")


async def _push_messages(to: str, messages: List[Dict[str, Any]]) -> None:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    if not to:
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": to,
        "messages": messages,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            detail = (resp.text or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            logger.warning("LINE push failed: status=%s body=%s", resp.status_code, detail)
            raise RuntimeError(f"line_push_failed_{resp.status_code}:{detail}")


async def _poll_imagen_job_and_push(*, line_user_id: str, job: Dict[str, Any]) -> None:
    job_id = str(job.get("job_id") or "").strip()
    status_url = str(job.get("status_url") or "").strip()
    preview_url = str(job.get("preview_url") or "").strip()
    result_url = str(job.get("result_url") or "").strip()

    poll_base = str(os.getenv("MCP_LINE_IMAGEN_POLL_BASE_URL", "http://mcp-imagen-light:8020") or "").strip().rstrip("/")

    def _rewrite_poll_url(u: str) -> str:
        u = (u or "").strip()
        if not u:
            return u
        if (u.startswith("https://line.idc1.surf-thailand.com/") or u.startswith("http://line.idc1.surf-thailand.com/")) and "/imagen/" in u and poll_base:
            path = u.split(".com", 1)[1]
            return poll_base + path
        return u

    status_url = _rewrite_poll_url(status_url)
    preview_url = _rewrite_poll_url(preview_url)
    result_url = _rewrite_poll_url(result_url)

    if not job_id or not result_url or not line_user_id:
        return

    poll_interval_s = float(os.getenv("MCP_LINE_IMAGEN_POLL_INTERVAL_SECONDS", "5"))
    max_previews = int(os.getenv("MCP_LINE_IMAGEN_MAX_PREVIEWS", "8"))
    max_seconds = float(os.getenv("MCP_LINE_IMAGEN_MAX_SECONDS", "1800"))

    last_preview_sig = ""
    previews_sent = 0
    started = time.time()

    timeout = httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            if (time.time() - started) > max_seconds:
                try:
                    await _push_messages(to=line_user_id, messages=[{"type": "text", "text": "Image generation timed out."}])
                except Exception:
                    return
                return

            if preview_url and previews_sent < max_previews:
                try:
                    r = await client.get(preview_url)
                    if r.status_code == 200 and str(r.headers.get("content-type") or "").lower().startswith("application/json"):
                        pj = r.json()
                        if isinstance(pj, dict) and pj.get("available") is True:
                            p_url = str(pj.get("url") or pj.get("image_url") or "").strip()
                            prog = pj.get("progress") if isinstance(pj.get("progress"), dict) else {}
                            sig = f"{p_url}|{prog.get('step')}|{prog.get('steps')}"
                            if p_url and sig != last_preview_sig:
                                last_preview_sig = sig
                                previews_sent += 1
                                await _push_messages(
                                    to=line_user_id,
                                    messages=[{"type": "image", "originalContentUrl": p_url, "previewImageUrl": p_url}],
                                )
                except Exception as exc:
                    logger.warning("imagen preview poll failed: job_id=%s err=%s", job_id, str(exc))

            try:
                r = await client.get(result_url)
                if r.status_code == 200 and str(r.headers.get("content-type") or "").lower().startswith("application/json"):
                    resj = r.json()
                    if isinstance(resj, dict) and resj.get("available") is True:
                        final_url = str(resj.get("url") or resj.get("image_url") or "").strip()
                        if final_url:
                            await _push_messages(
                                to=line_user_id,
                                messages=[{"type": "image", "originalContentUrl": final_url, "previewImageUrl": final_url}],
                            )
                            return
                elif r.status_code >= 500:
                    # If imagen-light rejects a suspicious/blank output, stop polling and notify user.
                    body = (r.text or "")[:500]
                    if "cuda_result_suspicious_image" in body:
                        await _push_messages(to=line_user_id, messages=[{"type": "text", "text": "Image generation failed: suspicious/blank output (black image)."}])
                        return
            except Exception as exc:
                logger.warning("imagen result poll failed: job_id=%s err=%s", job_id, str(exc))

            if status_url:
                try:
                    r = await client.get(status_url)
                    if r.status_code == 200 and str(r.headers.get("content-type") or "").lower().startswith("application/json"):
                        sj = r.json()
                        if isinstance(sj, dict) and sj.get("status") == "failed":
                            err = str(sj.get("error") or "job_failed").strip()
                            await _push_messages(to=line_user_id, messages=[{"type": "text", "text": f"Image generation failed: {err}"[:2000]}])
                            return
                except Exception:
                    pass

            await asyncio.sleep(max(1.0, poll_interval_s))


def _allowed_tools() -> List[str]:
    raw = (MCP_LINE_ALLOWED_TOOLS or "").strip()
    if not raw:
        return []
    # Accept either JSON array or comma-separated list
    if raw.startswith("["):
        try:
            import json

            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _one_mcp_accept_headers() -> Dict[str, str]:
    return {"Accept": "application/json, text/event-stream"}


def _one_mcp_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if ONE_MCP_BASIC_AUTH:
        headers["Authorization"] = f"Basic {ONE_MCP_BASIC_AUTH}"
    elif ONE_MCP_USERNAME and ONE_MCP_PASSWORD:
        pair = f"{ONE_MCP_USERNAME}:{ONE_MCP_PASSWORD}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(pair).decode("utf-8")
    return headers


def _parse_1mcp_response(resp: httpx.Response) -> Dict[str, Any]:
    ctype = str(resp.headers.get("content-type") or "").lower()
    if ctype.startswith("application/json"):
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    if "text/event-stream" in ctype:
        text = resp.text or ""
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    import json

                    data = json.loads(payload)
                    return data if isinstance(data, dict) else {}
                except Exception:
                    continue
        return {}

    return {}


async def _one_mcp_initialize_session() -> str:
    if not ONE_MCP_URL:
        raise RuntimeError("one_mcp_url_not_configured")

    init_payload: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "mcp-line", "version": "0.1"},
            "capabilities": {},
        },
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            ONE_MCP_URL,
            json=init_payload,
            headers={**_one_mcp_headers(), **_one_mcp_accept_headers()},
        )

    if resp.status_code >= 400:
        detail = (resp.text or "").strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        raise RuntimeError(f"one_mcp_init_failed_{resp.status_code}:{detail}")

    data = _parse_1mcp_response(resp)
    if not isinstance(data, dict) or "error" in data:
        raise RuntimeError(f"one_mcp_init_rpc_error:{(data or {}).get('error')}")

    session_id = str(resp.headers.get("mcp-session-id") or "").strip()
    if not session_id:
        result = data.get("result") or {}
        session_id = str(result.get("sessionId") or "").strip()
    if not session_id:
        raise RuntimeError("one_mcp_init_missing_session")

    inited_payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    async with httpx.AsyncClient(timeout=20.0) as client:
        _ = await client.post(
            ONE_MCP_URL,
            json=inited_payload,
            headers={
                **_one_mcp_headers(),
                **_one_mcp_accept_headers(),
                "mcp-session-id": session_id,
            },
        )

    return session_id


async def _invoke_mcp(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if not ONE_MCP_URL:
        raise RuntimeError("one_mcp_url_not_configured")
    allowed = _allowed_tools()
    if allowed and tool not in allowed:
        raise RuntimeError("tool_not_allowed")

    session_id = await _one_mcp_initialize_session()

    payload: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments or {}},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            ONE_MCP_URL,
            json=payload,
            headers={
                **_one_mcp_headers(),
                **_one_mcp_accept_headers(),
                "mcp-session-id": session_id,
            },
        )
        if resp.status_code >= 400:
            detail = (resp.text or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            raise RuntimeError(f"mcp_call_failed_{resp.status_code}:{detail}")
        data = _parse_1mcp_response(resp)
        if not isinstance(data, dict):
            return {"ok": True, "result": data}
        if "error" in data:
            raise RuntimeError(f"mcp_rpc_error:{data.get('error')}")
        return data


async def _agent_decide_and_reply(*, user_text: str) -> Dict[str, Any]:
    cleaned = (user_text or "").strip()
    if not cleaned:
        return {"type": "text", "text": "ok"}

    # Use the existing Glama MCP endpoint to decide a single action.
    # Output must be STRICT JSON: either reply_text or call_imagen.
    system_prompt = (
        "You are a LINE bot controller. Respond with ONLY valid JSON. "
        "You must choose exactly one action. "
        "Allowed actions: reply_text, call_imagen. "
        "Schemas: "
        "{\"action\":\"reply_text\",\"text\":string} "
        "OR {\"action\":\"call_imagen\",\"prompt\":string}. "
        "If user asks to generate an image, choose call_imagen. "
        "Keep text replies concise."
    )

    payload: Dict[str, Any] = {
        "tool": "chat_completion",
        "arguments": {
            "prompt": cleaned,
            "system_prompt": system_prompt,
        },
    }
    if GLAMA_MODEL:
        payload["arguments"]["model"] = GLAMA_MODEL

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(GLAMA_MCP_URL, json=payload)
    if resp.status_code >= 400:
        return {"type": "text", "text": f"ok: {cleaned}"}

    data = resp.json() if resp.headers.get("content-type", "").lower().startswith("application/json") else {}
    result = (data or {}).get("result") or {}
    assistant_text = str((result or {}).get("response") or "").strip()
    if not assistant_text:
        return {"type": "text", "text": f"ok: {cleaned}"}

    action_obj: Optional[Dict[str, Any]]
    try:
        import json

        action_obj = json.loads(assistant_text)
    except Exception:
        action_obj = None

    if not isinstance(action_obj, dict):
        return {"type": "text", "text": assistant_text[:2000]}

    action = str(action_obj.get("action") or "").strip()
    if action == "reply_text":
        text = str(action_obj.get("text") or "").strip() or "ok"
        return {"type": "text", "text": text[:2000]}

    if action == "call_imagen":
        prompt = str(action_obj.get("prompt") or "").strip() or cleaned
        tool = "mcp-imagen-light_1mcp_imagen_generate"
        res = await _invoke_mcp(tool, {"prompt": prompt})
        # 1mcp JSON-RPC returns {result:{content:[...]}} or similar; keep this tolerant.
        url = ""
        if isinstance(res, dict):
            result_obj = res.get("result")
            if isinstance(result_obj, dict):
                # If server returns a plain object {url:...}
                url = str(result_obj.get("url") or "").strip()
                # If server returns MCP content blocks
                if not url:
                    content = result_obj.get("content")
                    if isinstance(content, list) and content:
                        first = content[0] if isinstance(content[0], dict) else {}
                        url = str((first or {}).get("url") or "").strip()
                # Some adapters return {result:{result:"..."}}
                if not url:
                    url = str(result_obj.get("result") or "").strip()
        if not url:
            return {"type": "text", "text": "Image generated, but no URL was returned."}
        return {"type": "image", "originalContentUrl": url, "previewImageUrl": url}

    return {"type": "text", "text": assistant_text[:2000]}


async def _process_text_event_and_reply(*, evt: Dict[str, Any], reply_token: str) -> None:
    if not MCP_LINE_AGENT_ENABLED:
        return
    if not (MCP_ASSISTANT_URL or GLAMA_MCP_URL):
        return
    message = evt.get("message") or {}
    if not isinstance(message, dict):
        return
    if str(message.get("type") or "").strip() != "text":
        return
    user_text = str(message.get("text") or "")

    # Long-running work (LLM/tool calls) may exceed LINE replyToken lifetime.
    # Prefer push when we have a userId.
    line_user_id: str = ""
    src_obj = evt.get("source") or {}
    if isinstance(src_obj, dict):
        line_user_id = str(src_obj.get("userId") or "").strip()

    if line_user_id:
        logger.info("process_text_event: line_user_id=%s user_text_len=%s", line_user_id, len(user_text))
    else:
        logger.info("process_text_event: no_line_user_id user_text_len=%s", len(user_text))

    if MCP_ASSISTANT_URL:
        try:
            src = _conversation_source(evt) or {}
            src_type = str(src.get("type") or "").strip() or "unknown"
            src_id = str(src.get("id") or "").strip() or "unknown"
            conversation_id = _get_or_create_conversation(src_type, src_id)

            headers: Dict[str, str] = {}
            if MCP_ASSISTANT_CONTROL_TOKEN:
                headers["x-control-token"] = MCP_ASSISTANT_CONTROL_TOKEN

            payload: Dict[str, Any] = {
                "conversation_id": conversation_id,
                "text": user_text,
                "line_event": evt,
            }

            logger.info(
                "assistant request start: url=%s conversation_id=%s text_len=%s",
                f"{MCP_ASSISTANT_URL}/integrations/line/reply",
                conversation_id,
                len(user_text),
            )

            started = time.time()
            timeout = httpx.Timeout(connect=10.0, read=360.0, write=30.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{MCP_ASSISTANT_URL}/integrations/line/reply", json=payload, headers=headers)

            logger.info("assistant request done: elapsed_s=%.2f status=%s", (time.time() - started), resp.status_code)

            if resp.status_code >= 400:
                raise RuntimeError(f"assistant_http_{resp.status_code}")

            ct = str(resp.headers.get("content-type") or "")
            logger.info(
                "assistant http ok: status=%s content_type=%s body_len=%s",
                resp.status_code,
                ct,
                len(resp.content or b""),
            )

            data: Dict[str, Any] = {}
            if ct.lower().startswith("application/json"):
                try:
                    data = resp.json()
                except Exception as exc:
                    snippet = (resp.text or "")[:500]
                    logger.warning("assistant json parse failed: %s body=%s", str(exc), snippet)
                    data = {}
            messages = (data or {}).get("messages")
            if isinstance(messages, list) and messages:
                logger.info(
                    "assistant returned messages: count=%s delivery=%s",
                    len(messages),
                    "push" if line_user_id else ("reply" if reply_token else "none"),
                )
                if line_user_id:
                    await _push_messages(to=line_user_id, messages=messages)
                elif reply_token:
                    await _reply_messages(reply_token=reply_token, messages=messages)

                image_job = (data or {}).get("image_job")
                if line_user_id and isinstance(image_job, dict):
                    asyncio.create_task(_poll_imagen_job_and_push(line_user_id=line_user_id, job=image_job))
                return
        except Exception as exc:
            logger.warning("assistant forward failed: %s", str(exc))

    if not GLAMA_MCP_URL:
        return

    try:
        decision = await _agent_decide_and_reply(user_text=user_text)
        if isinstance(decision, dict) and decision.get("type") == "image":
            messages = [
                {
                    "type": "image",
                    "originalContentUrl": decision.get("originalContentUrl"),
                    "previewImageUrl": decision.get("previewImageUrl"),
                }
            ]
            if line_user_id:
                await _push_messages(to=line_user_id, messages=messages)
            elif reply_token:
                await _reply_messages(reply_token=reply_token, messages=messages)
            return
        text = str((decision or {}).get("text") or "ok")
        if line_user_id:
            await _push_messages(to=line_user_id, messages=[{"type": "text", "text": text}])
        elif reply_token:
            await _reply_message(reply_token=reply_token, text=text)
    except Exception as exc:
        logger.warning("agent processing failed: %s", str(exc))
        try:
            if line_user_id:
                await _push_messages(to=line_user_id, messages=[{"type": "text", "text": "Sorry, I had an error while processing that."}])
            elif reply_token:
                await _reply_message(reply_token=reply_token, text="Sorry, I had an error while processing that.")
        except Exception:
            return


async def _generate_reply(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return "ok"

    base_url = (GLAMA_MCP_URL or MCP_GLAMA_URL).strip().rstrip("/")
    if not (LINE_USE_GLAMA and base_url):
        return f"ok: {cleaned}"

    system_prompt = GLAMA_SYSTEM_PROMPT or "You are a helpful assistant replying to a LINE chat message. Keep replies concise."
    payload: Dict[str, Any] = {
        "tool": "chat_completion",
        "arguments": {
            "prompt": cleaned,
            "system_prompt": system_prompt,
        },
    }
    if GLAMA_MODEL:
        payload["arguments"]["model"] = GLAMA_MODEL

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base_url}/invoke", json=payload)
        if resp.status_code >= 400:
            logger.warning("Glama invoke failed: status=%s body=%s", resp.status_code, (resp.text or "").strip())
            return f"ok: {cleaned}"

        data = resp.json() if resp.headers.get("content-type", "").lower().startswith("application/json") else {}
        result = (data or {}).get("result") or {}
        out = (result or {}).get("response") or ""
        out = (out or "").strip()
        return out or f"ok: {cleaned}"
    except Exception as exc:
        logger.warning("Glama invoke exception: %s", str(exc))
        return f"ok: {cleaned}"


@app.get("/health")
async def health() -> Dict[str, Any]:
    base_url = (GLAMA_MCP_URL or MCP_GLAMA_URL).strip().rstrip("/")
    return {
        "status": "ok",
        "signatureConfigured": bool(LINE_CHANNEL_SECRET),
        "accessTokenConfigured": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "useGlama": bool(LINE_USE_GLAMA and base_url),
        "glamaUrl": base_url,
        "agentEnabled": bool(MCP_LINE_AGENT_ENABLED and (MCP_ASSISTANT_URL or GLAMA_MCP_URL)),
        "oneMcpUrl": ONE_MCP_URL,
        "allowedTools": _allowed_tools(),
        "dbPath": _get_db_path(),
        "controlAuthEnabled": bool(_get_control_token()),
    }


@app.post("/admin/link")
async def admin_link(request: Request) -> Dict[str, Any]:
    _require_control_auth(request)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_json: {exc}")

    line_user_id = str((body or {}).get("line_user_id") or "").strip()
    full_name = str((body or {}).get("full_name") or "").strip()
    if not line_user_id:
        raise HTTPException(status_code=400, detail="missing_line_user_id")
    if not full_name:
        raise HTTPException(status_code=400, detail="missing_full_name")

    conn = _get_conn()
    now = _utc_ts()
    person_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO people (person_id, full_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (person_id, full_name, now, now),
    )
    conn.execute(
        "INSERT INTO line_identities (line_user_id, person_id, created_at, last_seen_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(line_user_id) DO UPDATE SET person_id=excluded.person_id, last_seen_at=excluded.last_seen_at",
        (line_user_id, person_id, now, now),
    )
    conn.commit()

    return {"ok": True, "line_user_id": line_user_id, "person_id": person_id, "full_name": full_name}


@app.get("/admin/recent")
async def admin_recent(request: Request, limit: int = 50) -> Dict[str, Any]:
    _require_control_auth(request)
    limit = max(1, min(int(limit or 50), 200))
    conn = _get_conn()
    rows = conn.execute(
        "SELECT m.message_id, m.received_at, m.event_type, m.message_type, m.text, m.line_user_id, m.person_id, p.full_name, c.source_type, c.source_id "
        "FROM line_messages m "
        "LEFT JOIN people p ON p.person_id = m.person_id "
        "JOIN line_conversations c ON c.conversation_id = m.conversation_id "
        "ORDER BY m.received_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    items: List[Dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "message_id": r["message_id"],
                "received_at": r["received_at"],
                "event_type": r["event_type"],
                "message_type": r["message_type"],
                "text": r["text"],
                "line_user_id": r["line_user_id"],
                "person_id": r["person_id"],
                "full_name": r["full_name"],
                "conversation": {"type": r["source_type"], "id": r["source_id"]},
            }
        )
    return {"ok": True, "items": items}


@app.get("/admin/selftest_1mcp")
async def admin_selftest_1mcp(request: Request) -> Dict[str, Any]:
    _require_control_auth(request)

    if not ONE_MCP_URL:
        return {"ok": False, "error": "one_mcp_url_not_configured"}

    try:
        session_id = await _one_mcp_initialize_session()

        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                ONE_MCP_URL,
                json=payload,
                headers={
                    **_one_mcp_headers(),
                    **_one_mcp_accept_headers(),
                    "mcp-session-id": session_id,
                },
            )
        if resp.status_code >= 400:
            detail = (resp.text or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            return {"ok": False, "error": "one_mcp_http_error", "status": resp.status_code, "detail": detail}

        data = _parse_1mcp_response(resp)
        if not isinstance(data, dict):
            return {"ok": False, "error": "one_mcp_invalid_response", "raw": str(data)[:500]}
        if "error" in data:
            return {"ok": False, "error": "one_mcp_rpc_error", "rpc": data.get("error")}

        result = data.get("result") or {}
        tools = (result or {}).get("tools") or []
        names: List[str] = []
        if isinstance(tools, list):
            for t in tools:
                if isinstance(t, dict) and str(t.get("name") or "").strip():
                    names.append(str(t.get("name") or "").strip())

        expected = "mcp-imagen-light_1mcp_imagen_generate"
        return {
            "ok": True,
            "oneMcpUrl": ONE_MCP_URL,
            "toolCount": len(names),
            "expectedImagenTool": expected,
            "imagenToolPresent": expected in names,
            "allowedTools": _allowed_tools(),
        }
    except Exception as exc:
        return {"ok": False, "error": "selftest_exception", "detail": str(exc)}


@app.post("/webhook/line")
async def webhook_line(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: Optional[str] = Header(default=None, alias="X-Line-Signature"),
) -> Any:
    raw = await request.body()

    logger.info(
        "webhook_line raw: body_len=%s sig_present=%s sig_prefix=%s",
        len(raw or b""),
        bool(x_line_signature),
        str(x_line_signature or "")[:10],
    )

    if not _verify_line_signature(raw, x_line_signature):
        raise HTTPException(status_code=401, detail="invalid_signature")

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_json: {exc}")

    events: List[Dict[str, Any]] = body.get("events") or []

    logger.info("webhook_line received: events=%s", len(events))

    # Minimal behavior:
    # - If message event with a replyToken, echo back short text.
    # - Always return 200 quickly so LINE considers it delivered.
    reply_errors: List[str] = []

    for evt in events:
        try:
            src = _conversation_source(evt) or {}
            src_type = str(src.get("type") or "").strip()
            src_id = str(src.get("id") or "").strip()
            conversation_id = _get_or_create_conversation(src_type, src_id) if (src_type and src_id) else _get_or_create_conversation("unknown", "unknown")

            reply_token = evt.get("replyToken")
            evt_type = evt.get("type")
            message = evt.get("message") or {}
            message_type = message.get("type")
            text = message.get("text")

            logger.info(
                "webhook_line event: evt_type=%s message_type=%s has_reply_token=%s",
                str(evt_type or ""),
                str(message_type or ""),
                bool(reply_token),
            )

            line_user_id = None
            src_obj = evt.get("source") or {}
            if isinstance(src_obj, dict):
                line_user_id = str(src_obj.get("userId") or "").strip() or None

            if evt_type == "message" and message_type == "text":
                logger.info(
                    "webhook_line text: line_user_id=%s text_len=%s",
                    line_user_id or "",
                    len(str(text or "")),
                )
            if line_user_id:
                _upsert_line_identity(line_user_id)
            person_id = _person_id_for_line_user(line_user_id or "") if line_user_id else None

            _insert_line_event_message(
                conversation_id=conversation_id,
                evt=evt,
                line_user_id=line_user_id,
                person_id=person_id,
                event_type=str(evt_type or "unknown"),
                message_type=str(message_type) if message_type else None,
                text=str(text) if text is not None else None,
            )

            if evt_type == "message" and message_type == "text" and reply_token:
                # Fast webhook: run the heavy work in a background task.
                if MCP_LINE_AGENT_ENABLED and (MCP_ASSISTANT_URL or GLAMA_MCP_URL):
                    # Reply token is one-time use; acknowledge immediately, then push final result.
                    logger.info(
                        "processing ack delivery=%s",
                        "reply" if reply_token else "none",
                    )
                    logger.info("sending processing reply")
                    await _reply_message(reply_token=str(reply_token), text="Processing...")
                    logger.info("processing reply sent")
                    background_tasks.add_task(_process_text_event_and_reply, evt=evt, reply_token="")
                else:
                    reply_text = await _generate_reply(text=text or "")
                    await _reply_message(reply_token=reply_token, text=reply_text)
        except Exception as exc:
            logger.warning("webhook event processing failed: %s", str(exc))
            reply_errors.append(str(exc))

    return PlainTextResponse("OK")
