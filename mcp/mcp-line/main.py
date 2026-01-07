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
from fastapi.responses import JSONResponse

app = FastAPI()

logger = logging.getLogger("mcp-line")

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


async def _invoke_mcp(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if not ONE_MCP_URL:
        raise RuntimeError("one_mcp_url_not_configured")
    allowed = _allowed_tools()
    if allowed and tool not in allowed:
        raise RuntimeError("tool_not_allowed")

    headers: Dict[str, str] = {}
    if ONE_MCP_BASIC_AUTH:
        headers["Authorization"] = f"Basic {ONE_MCP_BASIC_AUTH}"
    elif ONE_MCP_USERNAME and ONE_MCP_PASSWORD:
        pair = f"{ONE_MCP_USERNAME}:{ONE_MCP_PASSWORD}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(pair).decode("utf-8")

    # 1mcp expects MCP JSON-RPC.
    payload: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/invoke",
        "params": {"name": tool, "arguments": arguments or {}},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(ONE_MCP_URL, json=payload, headers=headers)
        if resp.status_code >= 400:
            detail = (resp.text or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            raise RuntimeError(f"mcp_call_failed_{resp.status_code}:{detail}")
        data = resp.json() if resp.headers.get("content-type", "").lower().startswith("application/json") else {}
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

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{MCP_ASSISTANT_URL}/integrations/line/reply", json=payload, headers=headers)

            if resp.status_code >= 400:
                raise RuntimeError(f"assistant_http_{resp.status_code}")

            data = resp.json() if resp.headers.get("content-type", "").lower().startswith("application/json") else {}
            messages = (data or {}).get("messages")
            if isinstance(messages, list) and messages:
                await _reply_messages(reply_token=reply_token, messages=messages)
                return
        except Exception as exc:
            logger.warning("assistant forward failed: %s", str(exc))

    if not GLAMA_MCP_URL:
        return

    try:
        decision = await _agent_decide_and_reply(user_text=user_text)
        if isinstance(decision, dict) and decision.get("type") == "image":
            await _reply_messages(
                reply_token=reply_token,
                messages=[
                    {
                        "type": "image",
                        "originalContentUrl": decision.get("originalContentUrl"),
                        "previewImageUrl": decision.get("previewImageUrl"),
                    }
                ],
            )
            return
        text = str((decision or {}).get("text") or "ok")
        await _reply_message(reply_token=reply_token, text=text)
    except Exception as exc:
        logger.warning("agent processing failed: %s", str(exc))
        try:
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

    headers: Dict[str, str] = {}
    if ONE_MCP_BASIC_AUTH:
        headers["Authorization"] = f"Basic {ONE_MCP_BASIC_AUTH}"
    elif ONE_MCP_USERNAME and ONE_MCP_PASSWORD:
        pair = f"{ONE_MCP_USERNAME}:{ONE_MCP_PASSWORD}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(pair).decode("utf-8")

    payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(ONE_MCP_URL, json=payload, headers=headers)
        if resp.status_code >= 400:
            detail = (resp.text or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."
            return {"ok": False, "error": "one_mcp_http_error", "status": resp.status_code, "detail": detail}

        data = resp.json() if resp.headers.get("content-type", "").lower().startswith("application/json") else {}
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

    if not _verify_line_signature(raw, x_line_signature):
        raise HTTPException(status_code=401, detail="invalid_signature")

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_json: {exc}")

    events: List[Dict[str, Any]] = body.get("events") or []

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

            line_user_id = None
            src_obj = evt.get("source") or {}
            if isinstance(src_obj, dict):
                line_user_id = str(src_obj.get("userId") or "").strip() or None
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
                    background_tasks.add_task(_process_text_event_and_reply, evt=evt, reply_token=str(reply_token))
                else:
                    reply_text = await _generate_reply(text=text or "")
                    await _reply_message(reply_token=reply_token, text=reply_text)
        except Exception as exc:
            reply_errors.append(str(exc))

    return JSONResponse({"status": "ok", "events": len(events), "replyErrors": reply_errors})
