import asyncio
import base64
import os
import logging
import json
import sqlite3
import time
import uuid
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv

from google import genai
from google.genai import types


def _require_env(name: str) -> str:
    value = str(os.getenv(name, "") or "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


load_dotenv()

MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")

logger = logging.getLogger("jarvis-backend")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="jarvis-backend", version="0.1.0")


WEB_FETCHER_BASE_URL = str(os.getenv("WEB_FETCHER_BASE_URL") or "http://web-fetcher:8028").strip().rstrip("/")

MCP_BASE_URL = str(os.getenv("MCP_BASE_URL") or "http://mcp-bundle:3050").strip().rstrip("/")

AIM_MCP_BASE_URL = str(os.getenv("AIM_MCP_BASE_URL") or "").strip().rstrip("/")

WEAVIATE_URL = str(os.getenv("WEAVIATE_URL") or "").strip().rstrip("/")
GEMINI_EMBEDDING_MODEL = str(os.getenv("GEMINI_EMBEDDING_MODEL") or "text-embedding-004").strip() or "text-embedding-004"


SESSION_DB_PATH = os.getenv("JARVIS_SESSION_DB", "/app/jarvis_sessions.sqlite")

AGENTS_DIR = str(os.getenv("JARVIS_AGENTS_DIR") or "/app/agents").strip() or "/app/agents"

DEFAULT_USER_ID = str(os.getenv("JARVIS_DEFAULT_USER_ID") or "default").strip() or "default"
DEFAULT_TIMEZONE = str(os.getenv("JARVIS_DEFAULT_TIMEZONE") or "Asia/Bangkok").strip() or "Asia/Bangkok"
MORNING_BRIEF_HOUR = int(str(os.getenv("JARVIS_MORNING_BRIEF_HOUR") or "8").strip() or "8")
MORNING_BRIEF_MINUTE = int(str(os.getenv("JARVIS_MORNING_BRIEF_MINUTE") or "0").strip() or "0")

AGENT_CONTINUE_WINDOW_SECONDS = int(str(os.getenv("JARVIS_AGENT_CONTINUE_WINDOW_SECONDS") or "120").strip() or "120")

_ws_by_user: dict[str, set[WebSocket]] = {}
_reminder_task: Optional[asyncio.Task[None]] = None

_agent_defs: dict[str, dict[str, Any]] = {}

_agent_triggers: dict[str, list[str]] = {}

_weaviate_schema_ready: bool = False


def _init_session_db() -> None:
    os.makedirs(os.path.dirname(SESSION_DB_PATH) or ".", exist_ok=True)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              active_trip_id TEXT,
              active_trip_name TEXT,
              updated_at INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_writes (
              confirmation_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              action TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at INTEGER NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
              reminder_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              title TEXT NOT NULL,
              dedupe_key TEXT,
              due_at INTEGER,
              timezone TEXT NOT NULL,
              schedule_type TEXT NOT NULL,
              notify_at INTEGER NOT NULL,
              status TEXT NOT NULL,
              source_text TEXT,
              aim_entity_name TEXT,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_notify ON reminders(user_id, notify_at)")
        # Backwards-compatible migration: ensure dedupe_key exists for older DBs.
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(reminders)").fetchall()]
            if "dedupe_key" not in cols:
                conn.execute("ALTER TABLE reminders ADD COLUMN dedupe_key TEXT")
        except Exception:
            pass
        # Prevent duplicates among pending reminders.
        # SQLite supports partial indexes (>= 3.8.0), which is the norm on modern distros.
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_reminders_pending_dedupe ON reminders(user_id, dedupe_key) WHERE status = 'pending'"
            )
        except Exception:
            pass

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_status (
              user_id TEXT NOT NULL,
              agent_id TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY(user_id, agent_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_status_user_updated ON agent_status(user_id, updated_at)")
        conn.commit()


def _weaviate_enabled() -> bool:
    return bool(WEAVIATE_URL)


def _weaviate_object_uuid(external_key: str) -> str:
    # Deterministic UUID for idempotent upserts.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis::{external_key}"))


async def _gemini_embed_text(text: str) -> list[float]:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing required env var: API_KEY (or GEMINI_API_KEY)")
    client = genai.Client(api_key=api_key)
    # google-genai embedding API surface has changed across versions; try a couple patterns.
    try:
        res = await client.aio.models.embed_content(model=GEMINI_EMBEDDING_MODEL, contents=text)
        emb = getattr(res, "embedding", None)
        values = getattr(emb, "values", None)
        if isinstance(values, list) and values:
            return [float(x) for x in values]
    except Exception:
        pass
    try:
        res = await client.aio.models.embed_content(model=GEMINI_EMBEDDING_MODEL, content=text)
        emb = getattr(res, "embedding", None)
        values = getattr(emb, "values", None)
        if isinstance(values, list) and values:
            return [float(x) for x in values]
    except Exception as e:
        raise RuntimeError(f"gemini_embedding_failed: {e}")
    raise RuntimeError("gemini_embedding_failed")


async def _weaviate_request(method: str, path: str, payload: Any = None) -> Any:
    if not _weaviate_enabled():
        raise HTTPException(status_code=500, detail="weaviate_not_configured")
    url = f"{WEAVIATE_URL}{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.request(method, url, json=payload)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=502, detail={"weaviate_error": detail})
        if not res.text:
            return None
        try:
            return res.json()
        except Exception:
            return res.text


async def _weaviate_ensure_schema() -> None:
    global _weaviate_schema_ready
    if _weaviate_schema_ready:
        return
    if not _weaviate_enabled():
        return

    schema = {
        "class": "JarvisMemoryItem",
        "description": "Jarvis authoritative memory items (reminders, todos, notes, agent status).",
        "vectorizer": "none",
        "properties": [
            {"name": "external_key", "dataType": ["text"]},
            {"name": "kind", "dataType": ["text"]},
            {"name": "title", "dataType": ["text"]},
            {"name": "body", "dataType": ["text"]},
            {"name": "status", "dataType": ["text"]},
            {"name": "due_at", "dataType": ["number"]},
            {"name": "notify_at", "dataType": ["number"]},
            {"name": "timezone", "dataType": ["text"]},
            {"name": "source", "dataType": ["text"]},
            {"name": "created_at", "dataType": ["number"]},
            {"name": "updated_at", "dataType": ["number"]},
        ],
    }

    try:
        await _weaviate_request("GET", "/v1/schema/JarvisMemoryItem")
        _weaviate_schema_ready = True
        return
    except Exception:
        pass

    await _weaviate_request("POST", "/v1/schema", schema)
    _weaviate_schema_ready = True


async def _weaviate_upsert_memory_item(
    *,
    external_key: str,
    kind: str,
    title: str,
    body: str,
    status: str,
    due_at: Optional[int],
    notify_at: Optional[int],
    timezone_name: str,
    source: str,
) -> dict[str, Any]:
    await _weaviate_ensure_schema()
    now_ts = int(time.time())
    obj_id = _weaviate_object_uuid(external_key)

    vector_text = "\n".join([str(kind), str(title), str(body)]).strip()
    vector = await _gemini_embed_text(vector_text)

    existing_created_at: Optional[float] = None
    try:
        existing = await _weaviate_request("GET", f"/v1/objects/{obj_id}")
        if isinstance(existing, dict):
            props0 = existing.get("properties")
            if isinstance(props0, dict) and props0.get("created_at") is not None:
                try:
                    existing_created_at = float(props0.get("created_at"))
                except Exception:
                    existing_created_at = None
    except Exception:
        existing_created_at = None

    props: dict[str, Any] = {
        "external_key": external_key,
        "kind": kind,
        "title": title,
        "body": body,
        "status": status,
        "timezone": timezone_name,
        "source": source,
        "updated_at": now_ts,
    }
    if due_at is not None:
        props["due_at"] = float(due_at)
    if notify_at is not None:
        props["notify_at"] = float(notify_at)

    # First write uses created_at; subsequent writes keep the original created_at.
    if existing_created_at is not None:
        props["created_at"] = float(existing_created_at)
    else:
        props["created_at"] = float(now_ts)

    payload = {
        "class": "JarvisMemoryItem",
        "id": obj_id,
        "properties": props,
        "vector": vector,
    }

    await _weaviate_request("PUT", f"/v1/objects/{obj_id}", payload)
    return {"id": obj_id, "external_key": external_key}


async def _weaviate_query_upcoming_reminders(*, start_ts: int, end_ts: int, limit: int) -> list[dict[str, Any]]:
    await _weaviate_ensure_schema()
    lim = max(1, min(int(limit or 50), 500))
    query = {
        "query": """
        {
          Get {
            JarvisMemoryItem(
              where: {
                operator: And
                operands: [
                  { path: [\"kind\"], operator: Equal, valueText: \"reminder\" }
                  { path: [\"status\"], operator: Equal, valueText: \"pending\" }
                  { path: [\"notify_at\"], operator: GreaterThanEqual, valueNumber: %START% }
                  { path: [\"notify_at\"], operator: LessThanEqual, valueNumber: %END% }
                ]
              }
              limit: %LIMIT%
            ) {
              external_key
              title
              body
              status
              due_at
              notify_at
              timezone
              updated_at
            }
          }
        }
        """
        .replace("%START%", str(float(int(start_ts))))
        .replace("%END%", str(float(int(end_ts))))
        .replace("%LIMIT%", str(int(lim)))
    }
    res = await _weaviate_request("POST", "/v1/graphql", query)
    items = (
        res.get("data", {})
        .get("Get", {})
        .get("JarvisMemoryItem", [])
        if isinstance(res, dict)
        else []
    )
    out: list[dict[str, Any]] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                out.append(it)
    return out


def _local_reminder_id_from_external_key(external_key: str) -> str:
    s = str(external_key or "").strip()
    # Prefer decoding when possible to avoid generating new local ids for existing reminders.
    if s.startswith("reminder::"):
        tail = s[len("reminder::") :].strip()
        if tail:
            return tail
    # Stable local PK so restart sync can still upsert deterministically.
    u = uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis_local::{s}")
    return f"r_{u.hex[:18]}"


def _upsert_local_reminder_from_memory_item(user_id: str, item: dict[str, Any]) -> Optional[str]:
    external_key = str(item.get("external_key") or "").strip()
    if not external_key:
        return None
    reminder_id = _local_reminder_id_from_external_key(external_key)
    title = str(item.get("title") or "Reminder").strip() or "Reminder"
    tz_name = str(item.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    schedule_type = "memory"
    source_text = str(item.get("body") or "").strip()

    due_at = item.get("due_at")
    notify_at = item.get("notify_at")
    try:
        due_at_ts = int(float(due_at)) if due_at is not None else None
    except Exception:
        due_at_ts = None
    try:
        notify_at_ts = int(float(notify_at)) if notify_at is not None else None
    except Exception:
        notify_at_ts = None

    if notify_at_ts is None:
        return None

    dedupe_key = _reminder_dedupe_key(title, due_at_ts, schedule_type)

    _init_session_db()
    now_ts = int(time.time())
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO reminders(
              reminder_id, user_id, title, dedupe_key, due_at, timezone, schedule_type, notify_at, status,
              source_text, aim_entity_name, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reminder_id) DO UPDATE SET
              title=excluded.title,
              dedupe_key=excluded.dedupe_key,
              due_at=excluded.due_at,
              timezone=excluded.timezone,
              schedule_type=excluded.schedule_type,
              notify_at=excluded.notify_at,
              status=excluded.status,
              source_text=excluded.source_text,
              updated_at=excluded.updated_at
            """,
            (
                reminder_id,
                user_id,
                title,
                dedupe_key,
                due_at_ts,
                tz_name,
                schedule_type,
                notify_at_ts,
                "pending",
                source_text,
                external_key,
                now_ts,
                now_ts,
            ),
        )
        conn.commit()
    return reminder_id


def _parse_agent_md(md_text: str) -> Optional[dict[str, Any]]:
    text = str(md_text or "")
    if not text.strip().startswith("---"):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    meta: dict[str, Any] = {}
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            key = str(k).strip()
            val = str(v).strip()
            if key:
                meta[key] = val
        i += 1

    if i >= len(lines) or lines[i].strip() != "---":
        return None

    body = "\n".join(lines[i + 1 :]).strip()
    if body:
        meta["body"] = body
    return meta


def _load_agent_defs() -> dict[str, dict[str, Any]]:
    defs: dict[str, dict[str, Any]] = {}
    root = Path(AGENTS_DIR)
    if not root.exists() or not root.is_dir():
        return defs

    for p in sorted(root.rglob("*.md")):
        try:
            md = p.read_text(encoding="utf-8")
        except Exception:
            continue
        parsed = _parse_agent_md(md)
        if not isinstance(parsed, dict):
            continue
        agent_id = str(parsed.get("id") or "").strip()
        if not agent_id:
            continue
        parsed["path"] = str(p)
        defs[agent_id] = parsed
    return defs


def _agents_snapshot() -> dict[str, dict[str, Any]]:
    global _agent_defs
    if not _agent_defs:
        _agent_defs = _load_agent_defs()
    return dict(_agent_defs)


def _agent_triggers_snapshot() -> dict[str, list[str]]:
    global _agent_triggers
    if _agent_triggers:
        return dict(_agent_triggers)

    agents = _agents_snapshot()
    out: dict[str, list[str]] = {}
    for agent_id, meta in agents.items():
        raw = meta.get("trigger_phrases")
        if raw is None:
            continue
        phrases: list[str] = []
        if isinstance(raw, str):
            # Support simple comma-separated values (frontmatter is parsed as strings).
            for part in raw.split(","):
                p = part.strip()
                if p:
                    phrases.append(p)
        if phrases:
            out[agent_id] = phrases
    _agent_triggers = out
    return dict(_agent_triggers)


def _upsert_agent_status(user_id: str, agent_id: str, payload: Any) -> None:
    _init_session_db()
    now_ts = int(time.time())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO agent_status(user_id, agent_id, payload_json, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_id, agent_id) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (user_id, agent_id, payload_json, now_ts),
        )
        conn.commit()


def _get_agent_statuses(user_id: str) -> list[dict[str, Any]]:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT agent_id, payload_json, updated_at FROM agent_status WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for agent_id, payload_json, updated_at in rows:
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = payload_json
        out.append({"agent_id": agent_id, "payload": payload, "updated_at": updated_at})
    return out


def _list_upcoming_pending_reminders(
    *,
    user_id: str,
    start_ts: int,
    end_ts: int,
    time_field: str,
    limit: int,
) -> list[dict[str, Any]]:
    _init_session_db()
    field = str(time_field or "notify_at").strip().lower() or "notify_at"
    if field not in ("notify_at", "due_at"):
        raise HTTPException(status_code=400, detail="invalid_time_field")

    start_v = int(start_ts)
    end_v = int(end_ts)
    if end_v < start_v:
        raise HTTPException(status_code=400, detail="invalid_time_window")

    lim = max(1, min(int(limit or 50), 500))

    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            f"""
            SELECT reminder_id, title, due_at, timezone, schedule_type, notify_at, source_text, aim_entity_name
            FROM reminders
            WHERE user_id = ?
              AND status = 'pending'
              AND {field} IS NOT NULL
              AND {field} >= ?
              AND {field} <= ?
            ORDER BY {field} ASC
            LIMIT ?
            """,
            (user_id, start_v, end_v, lim),
        )
        rows = cur.fetchall() or []

    out: list[dict[str, Any]] = []
    for reminder_id, title, due_at, tz_name, schedule_type, notify_at, source_text, aim_entity_name in rows:
        out.append(
            {
                "reminder_id": reminder_id,
                "title": title,
                "due_at": due_at,
                "timezone": tz_name,
                "schedule_type": schedule_type,
                "notify_at": notify_at,
                "source_text": source_text,
                "aim_entity_name": aim_entity_name,
            }
        )
    return out


def _list_reminders(
    *,
    user_id: str,
    status: str,
    limit: int,
    offset: int,
    order: str,
) -> list[dict[str, Any]]:
    _init_session_db()
    status_norm = str(status or "all").strip().lower() or "all"
    order_norm = str(order or "desc").strip().lower() or "desc"
    lim = max(1, min(int(limit or 50), 500))
    off = max(0, int(offset or 0))

    if status_norm not in ("all", "pending", "fired"):
        raise HTTPException(status_code=400, detail="invalid_status")
    if order_norm not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="invalid_order")

    status_clause = ""
    params: list[Any] = [user_id]
    if status_norm != "all":
        status_clause = " AND status = ?"
        params.append(status_norm)

    sql = (
        "SELECT reminder_id, title, due_at, timezone, schedule_type, notify_at, status, source_text, aim_entity_name, created_at, updated_at "
        "FROM reminders "
        "WHERE user_id = ?" + status_clause + " "
        f"ORDER BY updated_at {order_norm.upper()} "
        "LIMIT ? OFFSET ?"
    )
    params.extend([lim, off])

    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(sql, tuple(params))
        rows = cur.fetchall() or []

    out: list[dict[str, Any]] = []
    for (
        reminder_id,
        title,
        due_at,
        tz_name,
        schedule_type,
        notify_at,
        status_value,
        source_text,
        aim_entity_name,
        created_at,
        updated_at,
    ) in rows:
        out.append(
            {
                "reminder_id": reminder_id,
                "title": title,
                "due_at": due_at,
                "timezone": tz_name,
                "schedule_type": schedule_type,
                "notify_at": notify_at,
                "status": status_value,
                "source_text": source_text,
                "aim_entity_name": aim_entity_name,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
    return out


def _render_daily_brief(user_id: str) -> dict[str, Any]:
    agents = _agents_snapshot()
    statuses = _get_agent_statuses(user_id)
    status_by_agent: dict[str, dict[str, Any]] = {}
    for s in statuses:
        aid = str(s.get("agent_id") or "").strip()
        if aid and aid not in status_by_agent:
            status_by_agent[aid] = s

    now_ts = int(time.time())
    upcoming_reminders = _list_upcoming_pending_reminders(
        user_id=user_id,
        start_ts=now_ts,
        end_ts=now_ts + 24 * 3600,
        time_field="notify_at",
        limit=50,
    )

    lines: list[str] = []
    lines.append(f"Daily Brief ({datetime.now(tz=_get_user_timezone(user_id)).isoformat()})")

    lines.append("\nAgents")
    for agent_id in sorted(agents.keys()):
        name = str(agents[agent_id].get("name") or agent_id)
        s = status_by_agent.get(agent_id)
        if not s:
            lines.append(f"- {name}: no recent status")
            continue
        payload = s.get("payload")
        summary = ""
        if isinstance(payload, dict):
            summary = str(payload.get("summary") or payload.get("status") or "").strip()
        updated_at = int(s.get("updated_at") or 0)
        when = datetime.fromtimestamp(updated_at, tz=timezone.utc).isoformat() if updated_at else ""
        if summary:
            lines.append(f"- {name}: {summary} ({when})")
        else:
            lines.append(f"- {name}: updated ({when})")

    if upcoming_reminders:
        lines.append("\nReminders (next 24h)")
        for r in upcoming_reminders[:20]:
            title = str(r.get("title") or "").strip() or "Reminder"
            notify_at = r.get("notify_at")
            due_at = r.get("due_at")
            lines.append(f"- {title} (notify_at={notify_at}, due_at={due_at})")

    return {
        "user_id": user_id,
        "generated_at": int(time.time()),
        "agent_count": len(agents),
        "status_count": len(statuses),
        "brief_text": "\n".join(lines).strip(),
    }


def _extract_reminder_setup_title(text: str) -> str:
    s = str(text or "").strip()
    m = re.search(r"\breminder\s+setup\b\s*[:\-]?\s*(.*)$", s, flags=re.IGNORECASE)
    if not m:
        return "Reminder"
    tail = str(m.group(1) or "").strip()
    if not tail:
        return "Reminder"
    # Keep titles short and stable.
    return tail[:120]


async def _handle_reminder_setup_trigger(ws: WebSocket, text: str) -> bool:
    title = _extract_reminder_setup_title(text)
    tz = _get_user_timezone(DEFAULT_USER_ID)
    now = datetime.now(tz=timezone.utc)
    due_at_utc, local_iso = _parse_time_from_text(text, now, tz)
    if due_at_utc is None:
        await ws.send_json(
            {
                "type": "error",
                "message": "reminder_setup_missing_time",
                "hint": "Include a time like 'today at 5pm' or 'tomorrow 09:00'.",
            }
        )
        return True

    # Weaviate-authoritative: write local first for reliability, then write-through to Weaviate.
    schedule_type = "morning_brief"
    notify_at_local = _next_morning_brief_at(now, tz, due_at_utc)
    notify_at_utc = notify_at_local.astimezone(timezone.utc)
    external_key: Optional[str] = None

    reminder_id = _create_reminder(
        user_id=DEFAULT_USER_ID,
        title=title,
        due_at_utc=due_at_utc,
        tz=tz,
        schedule_type=schedule_type,
        notify_at_utc=notify_at_utc,
        source_text=text,
        aim_entity_name=None,
    )

    external_key = f"reminder::{reminder_id}"

    result: Any = {
        "ok": True,
        "reminder": {
            "reminder_id": reminder_id,
            "schedule_type": schedule_type,
            "due_at_utc": due_at_utc.replace(tzinfo=timezone.utc).isoformat(),
            "local_time": local_iso,
            "timezone": tz.key,
        },
    }

    if _weaviate_enabled():
        try:
            wv = await _weaviate_upsert_memory_item(
                external_key=external_key,
                kind="reminder",
                title=title,
                body=text,
                status="pending",
                due_at=int(due_at_utc.timestamp()),
                notify_at=int(notify_at_utc.timestamp()),
                timezone_name=tz.key,
                source="jarvis",
            )
            # Store a stable mapping for later debug/sync.
            try:
                _init_session_db()
                with sqlite3.connect(SESSION_DB_PATH) as conn:
                    conn.execute(
                        "UPDATE reminders SET aim_entity_name = ?, updated_at = ? WHERE reminder_id = ?",
                        (external_key, int(time.time()), reminder_id),
                    )
                    conn.commit()
            except Exception:
                pass
            result = {**result, "weaviate": wv}
        except Exception as e:
            result = {**result, "weaviate": {"ok": False, "error": str(e)}}

    _upsert_agent_status(
        DEFAULT_USER_ID,
        "reminder-setup",
        {
            "summary": f"created reminder: {title}",
            "reminder_id": reminder_id,
            "result": result,
            "updated_at": int(time.time()),
        },
    )

    await ws.send_json(
        {
            "type": "reminder_setup",
            "title": title,
            "reminder_id": reminder_id,
            "result": result,
        }
    )
    return True


async def _startup_resync_from_weaviate() -> None:
    if not _weaviate_enabled():
        return
    try:
        now_ts = int(time.time())
        # Keep local scheduler warm for the next 7 days.
        items = await _weaviate_query_upcoming_reminders(
            start_ts=now_ts,
            end_ts=now_ts + 7 * 24 * 3600,
            limit=500,
        )
        for it in items:
            _upsert_local_reminder_from_memory_item(DEFAULT_USER_ID, it)
    except Exception as e:
        logger.warning("weaviate_startup_resync_failed error=%s", e)


async def _dispatch_sub_agents(ws: WebSocket, text: str) -> bool:
    # Continuation handling: if a sub-agent is active for this websocket, let it handle followups.
    now_ts = int(time.time())
    active_agent_id = str(getattr(ws.state, "active_agent_id", "") or "").strip() or None
    active_until = getattr(ws.state, "active_agent_until_ts", None)
    try:
        active_until_ts = int(active_until) if active_until is not None else 0
    except Exception:
        active_until_ts = 0

    async def _run_agent(agent_id: str) -> bool:
        agent_id_norm = str(agent_id or "").strip()
        if agent_id_norm == "reminder-setup":
            handled = await _handle_reminder_setup_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        return False

    if active_agent_id and active_until_ts >= now_ts:
        handled = await _run_agent(active_agent_id)
        if handled:
            return True

    # Trigger matching.
    triggers = _agent_triggers_snapshot()
    s = str(text or "")
    for agent_id, phrases in triggers.items():
        for phrase in phrases:
            if phrase and phrase.lower() in s.lower():
                handled = await _run_agent(agent_id)
                if handled:
                    return True

    # Clear expired continuation state.
    if active_agent_id and active_until_ts < now_ts:
        ws.state.active_agent_id = None
        ws.state.active_agent_until_ts = None
    return False


def _get_user_timezone(user_id: str) -> ZoneInfo:
    # Placeholder for future user-profile timezone retrieval.
    # For now, use a default timezone.
    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _next_morning_brief_at(now: datetime, tz: ZoneInfo, due_at: Optional[datetime]) -> datetime:
    base = due_at.astimezone(tz) if due_at is not None else now.astimezone(tz)
    candidate = datetime(
        year=base.year,
        month=base.month,
        day=base.day,
        hour=MORNING_BRIEF_HOUR,
        minute=MORNING_BRIEF_MINUTE,
        tzinfo=tz,
    )
    if candidate <= now.astimezone(tz):
        candidate = candidate + timedelta(days=1)
    return candidate


def _parse_time_from_text(text: str, now: datetime, tz: ZoneInfo) -> tuple[Optional[datetime], Optional[str]]:
    s = str(text or "").strip().lower()
    if not s:
        return None, None

    day: Optional[datetime] = None
    if re.search(r"\btomorrow\b", s):
        local = now.astimezone(tz)
        day = datetime(local.year, local.month, local.day, tzinfo=tz) + timedelta(days=1)
    elif re.search(r"\btoday\b", s):
        local = now.astimezone(tz)
        day = datetime(local.year, local.month, local.day, tzinfo=tz)

    time_match = re.search(r"\b(at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", s)
    if not time_match and day is None:
        return None, None

    hour = 9
    minute = 0
    meridiem = None
    if time_match:
        hour = int(time_match.group(2))
        minute = int(time_match.group(3) or "0")
        meridiem = time_match.group(4)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0

    if day is None:
        local = now.astimezone(tz)
        day = datetime(local.year, local.month, local.day, tzinfo=tz)
        # If time already passed today, treat it as tomorrow.
        candidate = day.replace(hour=hour, minute=minute)
        if candidate <= local:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(timezone.utc), f"{candidate.isoformat()}"

    candidate = day.replace(hour=hour, minute=minute)
    return candidate.astimezone(timezone.utc), f"{candidate.isoformat()}"


def _reminder_dedupe_key(title: str, due_at_ts: Optional[int], schedule_type: str) -> str:
    t = " ".join(str(title or "").strip().lower().split())
    d = str(int(due_at_ts)) if due_at_ts is not None else "none"
    s = " ".join(str(schedule_type or "").strip().lower().split())
    return f"{t}|{d}|{s}"[:512]


def _create_reminder(
    *,
    user_id: str,
    title: str,
    due_at_utc: Optional[datetime],
    tz: ZoneInfo,
    schedule_type: str,
    notify_at_utc: datetime,
    source_text: str,
    aim_entity_name: Optional[str],
) -> str:
    _init_session_db()
    now_ts = int(time.time())
    due_at_ts = int(due_at_utc.timestamp()) if due_at_utc is not None else None
    notify_at_ts = int(notify_at_utc.timestamp())
    dedupe_key = _reminder_dedupe_key(title, due_at_ts, schedule_type)

    with sqlite3.connect(SESSION_DB_PATH) as conn:
        # If an equivalent pending reminder already exists, reuse it and update notify_at to the earliest.
        cur = conn.execute(
            """
            SELECT reminder_id, notify_at
            FROM reminders
            WHERE user_id = ? AND dedupe_key = ? AND status = 'pending'
            LIMIT 1
            """,
            (user_id, dedupe_key),
        )
        row = cur.fetchone()
        if row:
            existing_id, existing_notify_at = row
            try:
                existing_notify_at_int = int(existing_notify_at)
            except Exception:
                existing_notify_at_int = notify_at_ts
            new_notify_at = min(existing_notify_at_int, notify_at_ts)
            conn.execute(
                "UPDATE reminders SET notify_at = ?, updated_at = ? WHERE reminder_id = ?",
                (new_notify_at, now_ts, existing_id),
            )
            conn.commit()
            return str(existing_id)

        reminder_id = f"r_{int(time.time())}_{os.urandom(6).hex()}"
        conn.execute(
            """
            INSERT INTO reminders(
              reminder_id, user_id, title, dedupe_key, due_at, timezone, schedule_type, notify_at, status,
              source_text, aim_entity_name, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """ ,
            (
                reminder_id,
                user_id,
                title,
                dedupe_key,
                due_at_ts,
                str(tz.key),
                schedule_type,
                notify_at_ts,
                "pending",
                source_text,
                aim_entity_name,
                now_ts,
                now_ts,
            ),
        )
        conn.commit()
    return reminder_id


def _mark_reminder_fired(reminder_id: str) -> None:
    _init_session_db()
    now_ts = int(time.time())
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            "UPDATE reminders SET status = ?, updated_at = ? WHERE reminder_id = ?",
            ("fired", now_ts, reminder_id),
        )
        conn.commit()


def _list_due_reminders(user_id: str, now_ts: int) -> list[dict[str, Any]]:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            """
            SELECT reminder_id, title, due_at, timezone, schedule_type, notify_at, source_text, aim_entity_name
            FROM reminders
            WHERE user_id = ? AND status = 'pending' AND notify_at <= ?
            ORDER BY notify_at ASC
            """,
            (user_id, now_ts),
        )
        rows = cur.fetchall() or []

    out: list[dict[str, Any]] = []
    for reminder_id, title, due_at, tz_name, schedule_type, notify_at, source_text, aim_entity_name in rows:
        out.append(
            {
                "reminder_id": reminder_id,
                "title": title,
                "due_at": due_at,
                "timezone": tz_name,
                "schedule_type": schedule_type,
                "notify_at": notify_at,
                "source_text": source_text,
                "aim_entity_name": aim_entity_name,
            }
        )
    return out


async def _broadcast_to_user(user_id: str, payload: dict[str, Any]) -> None:
    conns = list(_ws_by_user.get(user_id, set()))
    if not conns:
        return
    dead: list[WebSocket] = []
    for ws in conns:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    if dead:
        s = _ws_by_user.get(user_id)
        if s is not None:
            for ws in dead:
                s.discard(ws)


async def _reminder_scheduler_loop() -> None:
    while True:
        try:
            now_ts = int(time.time())
            reminders = _list_due_reminders(DEFAULT_USER_ID, now_ts)
            for r in reminders:
                reminder_id = str(r.get("reminder_id") or "")
                if reminder_id:
                    _mark_reminder_fired(reminder_id)
                await _broadcast_to_user(
                    DEFAULT_USER_ID,
                    {
                        "type": "reminder",
                        "reminder": r,
                    },
                )
        except Exception as e:
            logger.warning("reminder_scheduler_error error=%s", e)
        await asyncio.sleep(15)


@app.on_event("startup")
async def _startup() -> None:
    global _reminder_task
    try:
        _init_session_db()
    except Exception as e:
        logger.warning("session_db_init_failed error=%s", e)
    try:
        await _startup_resync_from_weaviate()
    except Exception as e:
        logger.warning("startup_resync_failed error=%s", e)
    if _reminder_task is None or _reminder_task.done():
        _reminder_task = asyncio.create_task(_reminder_scheduler_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _reminder_task
    if _reminder_task is not None:
        _reminder_task.cancel()
        _reminder_task = None


def _get_session_state(session_id: str) -> dict[str, Optional[str]]:
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT active_trip_id, active_trip_name FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"active_trip_id": None, "active_trip_name": None}
        return {"active_trip_id": row[0], "active_trip_name": row[1]}


def _set_session_state(session_id: str, active_trip_id: Optional[str], active_trip_name: Optional[str]) -> None:
    now = int(time.time())
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions(session_id, active_trip_id, active_trip_name, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              active_trip_id=excluded.active_trip_id,
              active_trip_name=excluded.active_trip_name,
              updated_at=excluded.updated_at
            """,
            (session_id, active_trip_id, active_trip_name, now),
        )
        conn.commit()


def _create_pending_write(session_id: str, action: str, payload: Any) -> str:
    _init_session_db()
    confirmation_id = f"pw_{int(time.time())}_{os.urandom(6).hex()}"
    created_at = int(time.time())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO pending_writes(confirmation_id, session_id, action, payload_json, created_at) VALUES(?, ?, ?, ?, ?)",
            (confirmation_id, session_id, action, payload_json, created_at),
        )
        conn.commit()
    return confirmation_id


def _list_pending_writes(session_id: str) -> list[dict[str, Any]]:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT confirmation_id, action, payload_json, created_at FROM pending_writes WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for confirmation_id, action, payload_json, created_at in rows:
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = payload_json
        out.append(
            {
                "confirmation_id": confirmation_id,
                "action": action,
                "payload": payload,
                "created_at": created_at,
            }
        )
    return out


def _pop_pending_write(session_id: str, confirmation_id: str) -> Optional[dict[str, Any]]:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT action, payload_json, created_at FROM pending_writes WHERE session_id = ? AND confirmation_id = ?",
            (session_id, confirmation_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        action, payload_json, created_at = row
        conn.execute(
            "DELETE FROM pending_writes WHERE session_id = ? AND confirmation_id = ?",
            (session_id, confirmation_id),
        )
        conn.commit()
    try:
        payload = json.loads(payload_json)
    except Exception:
        payload = payload_json
    return {"action": action, "payload": payload, "created_at": created_at}


def _cancel_pending_write(session_id: str, confirmation_id: str) -> bool:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM pending_writes WHERE session_id = ? AND confirmation_id = ?",
            (session_id, confirmation_id),
        )
        conn.commit()
        return (cur.rowcount or 0) > 0

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"] ,
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "jarvis-backend"}


@app.get("/agents")
def list_agents() -> dict[str, Any]:
    agents = _agents_snapshot()
    out: list[dict[str, Any]] = []
    for agent_id, meta in agents.items():
        out.append(
            {
                "id": agent_id,
                "name": meta.get("name") or agent_id,
                "kind": meta.get("kind") or "",
                "version": meta.get("version") or "",
                "path": meta.get("path") or "",
            }
        )
    return {"ok": True, "agents": out}


@app.post("/agents/{agent_id}/status")
def post_agent_status(agent_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    agents = _agents_snapshot()
    agent_id = str(agent_id or "").strip()
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail="agent_not_found")
    _upsert_agent_status(DEFAULT_USER_ID, agent_id, payload)
    return {"ok": True}


@app.get("/daily-brief")
def daily_brief() -> dict[str, Any]:
    agents = _agents_snapshot()
    if "daily-brief" not in agents:
        raise HTTPException(status_code=500, detail="daily_brief_agent_missing")
    return {"ok": True, "brief": _render_daily_brief(DEFAULT_USER_ID)}


@app.get("/reminders")
def list_reminders(status: str = "all", limit: int = 50, offset: int = 0, order: str = "desc") -> dict[str, Any]:
    reminders = _list_reminders(user_id=DEFAULT_USER_ID, status=status, limit=limit, offset=offset, order=order)
    return {"ok": True, "reminders": reminders}


@app.get("/reminders/upcoming")
def upcoming_reminders(window_hours: int = 48, time_field: str = "notify_at", limit: int = 50) -> dict[str, Any]:
    now_ts = int(time.time())
    end_ts = now_ts + max(1, int(window_hours or 48)) * 3600
    reminders = _list_upcoming_pending_reminders(
        user_id=DEFAULT_USER_ID,
        start_ts=now_ts,
        end_ts=end_ts,
        time_field=time_field,
        limit=limit,
    )
    return {"ok": True, "now": now_ts, "end": end_ts, "time_field": time_field, "reminders": reminders}


@app.get("/debug/agents")
def debug_agents() -> dict[str, Any]:
    agents = _agents_snapshot()
    triggers = _agent_triggers_snapshot()
    return {
        "ok": True,
        "agents_dir": AGENTS_DIR,
        "agent_count": len(agents),
        "agents": agents,
        "triggers": triggers,
        "continuation_window_seconds": AGENT_CONTINUE_WINDOW_SECONDS,
    }


def _parse_sse_first_message_data(text: str) -> dict[str, Any]:
    # 1MCP returns text/event-stream where each JSON-RPC response is on a `data: {...}` line.
    for line in (text or "").splitlines():
        if line.startswith("data: "):
            try:
                parsed = json.loads(line[len("data: ") :].strip())
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


async def _mcp_rpc(method: str, params: dict[str, Any]) -> Any:
    return await _mcp_rpc_base(MCP_BASE_URL, method, params)


async def _aim_mcp_rpc(method: str, params: dict[str, Any]) -> Any:
    if not AIM_MCP_BASE_URL:
        raise HTTPException(status_code=500, detail="aim_mcp_base_url_not_configured")
    return await _mcp_rpc_base(AIM_MCP_BASE_URL, method, params)


async def _mcp_rpc_base(base_url: str, method: str, params: dict[str, Any]) -> Any:
    session_id = str(uuid.uuid4())
    url = f"{base_url}/mcp?sessionId={session_id}"

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

        msg = _parse_sse_first_message_data(res.text)
        if msg.get("error") is not None:
            raise HTTPException(status_code=502, detail={"mcp_error": msg.get("error")})
        return msg.get("result")


async def _mcp_tools_list() -> list[dict[str, Any]]:
    result = await _mcp_rpc("tools/list", {})
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return []
    out: list[dict[str, Any]] = []
    for t in tools:
        if isinstance(t, dict) and isinstance(t.get("name"), str):
            out.append(t)
    return out


async def _mcp_tools_call(name: str, arguments: dict[str, Any]) -> Any:
    return await _mcp_rpc("tools/call", {"name": name, "arguments": arguments})


async def _aim_mcp_tools_call(name: str, arguments: dict[str, Any]) -> Any:
    return await _aim_mcp_rpc("tools/call", {"name": name, "arguments": arguments})


async def _web_fetcher_post(path: str, payload: Any) -> Any:
    url = f"{WEB_FETCHER_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.post(url, json=payload)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=res.status_code, detail=detail)
        return res.json()


def _require_confirmation(confirm: bool, action: str, payload: Any) -> None:
    if confirm:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "requires_confirmation": True,
            "action": action,
            "payload": payload,
        },
    )


def _adapt_aim_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name != "aim_memory_store":
        return args

    if isinstance(args.get("entities"), list):
        return args

    name = str(args.get("name") or "").strip() or "Memory"
    description = str(args.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="missing_description")

    entity_type = str(args.get("entityType") or args.get("entity_type") or "note").strip() or "note"
    tz = _get_user_timezone(DEFAULT_USER_ID)
    now = datetime.now(tz=timezone.utc)
    due_at_utc, local_iso = _parse_time_from_text(description, now, tz)
    if due_at_utc is not None:
        entity_type = "reminder"
    observations = args.get("observations")
    if not isinstance(observations, list):
        observations = [description]
    else:
        # Normalize observations to strings
        observations = [str(o) for o in observations if str(o).strip()]
        if not observations:
            observations = [description]

    if due_at_utc is not None and local_iso is not None:
        observations = list(observations)
        observations.append(f"TIMEZONE: {tz.key}")
        observations.append(f"ISO_TIME: {due_at_utc.replace(tzinfo=timezone.utc).isoformat()}")
        observations.append(f"LOCAL_TIME: {local_iso}")

    out: dict[str, Any] = {}
    context = args.get("context")
    if context is not None:
        out["context"] = str(context)
    location = args.get("location")
    if location is not None:
        out["location"] = str(location)

    out["entities"] = [
        {
            "name": name,
            "entityType": entity_type,
            "observations": observations,
        }
    ]
    return out


MCP_TOOL_MAP: dict[str, dict[str, Any]] = {
    "web_fetch": {
        "mcp_name": "fetch_1mcp_fetch",
        "description": "Fetch and extract readable text from a URL via the 1MCP fetch server.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "HTTP(S) URL to fetch."},
                "max_length": {"type": "integer", "description": "Maximum number of characters to return."},
                "start_index": {"type": "integer", "description": "Start content from this character index."},
                "raw": {"type": "boolean", "description": "Return raw content without markdown conversion."},
            },
            "required": ["url"],
        },
        "requires_confirmation": False,
    },
    "sequential_thinking": {
        "mcp_name": "server-sequential-thinking_1mcp_sequentialthinking",
        "description": "Run a step of Sequential Thinking (via 1MCP).",
        "parameters": {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "nextThoughtNeeded": {"type": "boolean"},
                "thoughtNumber": {"type": "integer"},
                "totalThoughts": {"type": "integer"},
                "isRevision": {"type": "boolean"},
                "revisesThought": {"type": "integer"},
                "branchFromThought": {"type": "integer"},
                "branchId": {"type": "string"},
                "needsMoreThoughts": {"type": "boolean"},
            },
            "required": ["thought", "nextThoughtNeeded", "thoughtNumber", "totalThoughts"],
        },
        "requires_confirmation": False,
    },
    "browser_navigate": {
        "mcp_name": "playwright_1mcp_browser_navigate",
        "description": "Navigate the browser to a URL (via 1MCP Playwright). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
        "requires_confirmation": True,
    },
    "browser_snapshot": {
        "mcp_name": "playwright_1mcp_browser_snapshot",
        "description": "Capture an accessibility snapshot of the page (via 1MCP Playwright).",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
            },
        },
        "requires_confirmation": False,
    },
    "browser_click": {
        "mcp_name": "playwright_1mcp_browser_click",
        "description": "Click an element (via 1MCP Playwright). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "element": {"type": "string"},
                "ref": {"type": "string"},
            },
            "required": ["ref"],
        },
        "requires_confirmation": True,
    },
    "browser_type": {
        "mcp_name": "playwright_1mcp_browser_type",
        "description": "Type into an element (via 1MCP Playwright). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "element": {"type": "string"},
                "ref": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["ref", "text"],
        },
        "requires_confirmation": True,
    },
    "browser_wait_for": {
        "mcp_name": "playwright_1mcp_browser_wait_for",
        "description": "Wait for text or time (via 1MCP Playwright).",
        "parameters": {
            "type": "object",
            "properties": {
                "time": {"type": "number"},
                "text": {"type": "string"},
                "textGone": {"type": "string"},
            },
        },
        "requires_confirmation": False,
    },

    "aim_memory_store": {
        "mcp_name": "aim-kg_1mcp_aim_memory_store",
        "description": "Store entities/observations in the AIM knowledge graph memory store.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Optional memory context. Defaults to master database if not specified.",
                },
                "location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Optional storage location override.",
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "The name of the entity"},
                            "entityType": {"type": "string", "description": "The type of the entity"},
                            "observations": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Observations associated with the entity",
                            },
                        },
                        "required": ["name", "entityType", "observations"],
                    },
                },
            },
            "required": ["entities"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_add_facts": {
        "mcp_name": "aim-kg_1mcp_aim_memory_add_facts",
        "description": "Add facts/observations to an existing memory entity.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Optional memory context."},
                "location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Optional storage location override.",
                },
                "observations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entityName": {"type": "string"},
                            "contents": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["entityName", "contents"],
                    },
                },
            },
            "required": ["observations"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_link": {
        "mcp_name": "aim-kg_1mcp_aim_memory_link",
        "description": "Link two memory entities together.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Optional memory context."},
                "location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Optional storage location override.",
                },
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "relationType": {"type": "string"},
                        },
                        "required": ["from", "to", "relationType"],
                    },
                },
            },
            "required": ["relations"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_search": {
        "mcp_name": "aim-kg_1mcp_aim_memory_search",
        "description": "Search memory entities by keyword.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "query": {"type": "string"},
                "format": {"type": "string", "enum": ["json", "pretty"]},
            },
            "required": ["query"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_get": {
        "mcp_name": "aim-kg_1mcp_aim_memory_get",
        "description": "Get memory entities by exact name.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "names": {"type": "array", "items": {"type": "string"}},
                "format": {"type": "string", "enum": ["json", "pretty"]},
            },
            "required": ["names"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_read_all": {
        "mcp_name": "aim-kg_1mcp_aim_memory_read_all",
        "description": "Read all memories from a store.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "format": {"type": "string", "enum": ["json", "pretty"]},
            },
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_list_stores": {
        "mcp_name": "aim-kg_1mcp_aim_memory_list_stores",
        "description": "List available memory stores/databases.",
        "parameters": {"type": "object", "properties": {}},
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_forget": {
        "mcp_name": "aim-kg_1mcp_aim_memory_forget",
        "description": "Forget/delete memories.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "entityNames": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["entityNames"],
        },
        "requires_confirmation": True,
        "mcp_base": "aim",
    },
    "aim_memory_remove_facts": {
        "mcp_name": "aim-kg_1mcp_aim_memory_remove_facts",
        "description": "Remove facts from an existing memory entity.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "deletions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entityName": {"type": "string"},
                            "observations": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["entityName", "observations"],
                    },
                },
            },
            "required": ["deletions"],
        },
        "requires_confirmation": True,
        "mcp_base": "aim",
    },
    "aim_memory_unlink": {
        "mcp_name": "aim-kg_1mcp_aim_memory_unlink",
        "description": "Remove links between memory entities.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "relationType": {"type": "string"},
                        },
                        "required": ["from", "to", "relationType"],
                    },
                },
            },
            "required": ["relations"],
        },
        "requires_confirmation": True,
        "mcp_base": "aim",
    },
}


def _mcp_tool_declarations() -> list[dict[str, Any]]:
    decls: list[dict[str, Any]] = []
    for name, meta in MCP_TOOL_MAP.items():
        decl: dict[str, Any] = {
            "name": name,
            "description": str(meta.get("description") or ""),
        }
        params = meta.get("parameters")
        if isinstance(params, dict):
            decl["parameters"] = params
        decls.append(decl)

    decls.append({"name": "pending_list", "description": "List queued pending actions waiting for confirmation."})
    decls.append(
        {
            "name": "pending_confirm",
            "description": "Confirm and execute a queued pending action.",
            "parameters": {
                "type": "object",
                "properties": {"confirmation_id": {"type": "string"}},
                "required": ["confirmation_id"],
            },
        }
    )
    decls.append(
        {
            "name": "pending_cancel",
            "description": "Cancel a queued pending action.",
            "parameters": {
                "type": "object",
                "properties": {"confirmation_id": {"type": "string"}},
                "required": ["confirmation_id"],
            },
        }
    )

    decls.append(
        {
            "name": "reminders_list",
            "description": "List reminders from the local Jarvis session DB (including fired/old reminders).",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status: all|pending|fired"},
                    "limit": {"type": "integer", "description": "Max rows (default 50, max 500)"},
                    "offset": {"type": "integer", "description": "Offset for pagination"},
                    "order": {"type": "string", "description": "Sort by updated_at: asc|desc"},
                },
            },
        }
    )

    decls.append(
        {
            "name": "reminders_upcoming",
            "description": "List upcoming pending reminders in the next N hours (defaults to 48).",
            "parameters": {
                "type": "object",
                "properties": {
                    "window_hours": {"type": "integer", "description": "How far ahead to look (hours)."},
                    "time_field": {
                        "type": "string",
                        "description": "Which timestamp to use: notify_at|due_at (default notify_at).",
                    },
                    "limit": {"type": "integer", "description": "Max rows (default 50, max 500)."},
                },
            },
        }
    )
    return decls


async def _handle_mcp_tool_call(session_id: Optional[str], tool_name: str, args: dict[str, Any]) -> Any:
    if tool_name == "pending_list":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        return _list_pending_writes(session_id)

    if tool_name == "pending_confirm":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        pending = _pop_pending_write(session_id, confirmation_id)
        if not pending:
            raise HTTPException(status_code=404, detail="pending_write_not_found")
        action = str(pending.get("action") or "")
        payload = pending.get("payload")
        if action == "mcp_tools_call":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            mcp_name = str(payload.get("mcp_name") or "")
            mcp_args = payload.get("arguments")
            mcp_base = str(payload.get("mcp_base") or "").strip().lower()
            original_tool_name = str(payload.get("tool_name") or "").strip()
            if not mcp_name or not isinstance(mcp_args, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            if mcp_base == "aim":
                adapted = _adapt_aim_tool_args(original_tool_name or "", dict(mcp_args))
                return await _aim_mcp_tools_call(mcp_name, adapted)
            return await _mcp_tools_call(mcp_name, mcp_args)
        raise HTTPException(status_code=400, detail={"unknown_pending_action": action})

    if tool_name == "pending_cancel":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        ok = _cancel_pending_write(session_id, confirmation_id)
        if not ok:
            raise HTTPException(status_code=404, detail="pending_write_not_found")
        return {"ok": True}

    if tool_name == "reminders_list":
        status = str(args.get("status") or "all")
        limit = int(args.get("limit") or 50)
        offset = int(args.get("offset") or 0)
        order = str(args.get("order") or "desc")
        return _list_reminders(user_id=DEFAULT_USER_ID, status=status, limit=limit, offset=offset, order=order)

    if tool_name == "reminders_upcoming":
        window_hours = int(args.get("window_hours") or 48)
        time_field = str(args.get("time_field") or "notify_at")
        limit = int(args.get("limit") or 50)
        now_ts = int(time.time())
        end_ts = now_ts + max(1, window_hours) * 3600
        return _list_upcoming_pending_reminders(
            user_id=DEFAULT_USER_ID,
            start_ts=now_ts,
            end_ts=end_ts,
            time_field=time_field,
            limit=limit,
        )

    meta = MCP_TOOL_MAP.get(tool_name)
    if not meta:
        raise HTTPException(status_code=400, detail={"unknown_tool": tool_name})

    mcp_name = str(meta.get("mcp_name") or "")
    if not mcp_name:
        raise HTTPException(status_code=500, detail="mcp_tool_missing_mapping")

    requires_confirmation = bool(meta.get("requires_confirmation"))
    mcp_base = str(meta.get("mcp_base") or "").strip().lower()
    if requires_confirmation:
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        confirmation_id = _create_pending_write(
            session_id,
            action="mcp_tools_call",
            payload={"mcp_name": mcp_name, "arguments": dict(args), "mcp_base": mcp_base, "tool_name": tool_name},
        )
        return {
            "requires_confirmation": True,
            "confirmation_id": confirmation_id,
            "action": tool_name,
            "payload": args,
        }

    if mcp_base == "aim":
        adapted = _adapt_aim_tool_args(tool_name, dict(args))
        result = await _aim_mcp_tools_call(mcp_name, adapted)

        if tool_name == "aim_memory_store":
            try:
                entities = adapted.get("entities")
                if isinstance(entities, list) and entities:
                    ent0 = entities[0] if isinstance(entities[0], dict) else {}
                    title = str(ent0.get("name") or "Reminder").strip() or "Reminder"
                    obs = ent0.get("observations")
                    source_text = ""
                    if isinstance(obs, list) and obs:
                        source_text = str(obs[0])

                    tz = _get_user_timezone(DEFAULT_USER_ID)
                    now = datetime.now(tz=timezone.utc)
                    due_at_utc, _ = _parse_time_from_text(source_text, now, tz)
                    if due_at_utc is not None:
                        schedule_type = "morning_brief"
                        notify_at_local = _next_morning_brief_at(now, tz, due_at_utc)
                        notify_at_utc = notify_at_local.astimezone(timezone.utc)
                        reminder_id = _create_reminder(
                            user_id=DEFAULT_USER_ID,
                            title=title,
                            due_at_utc=due_at_utc,
                            tz=tz,
                            schedule_type=schedule_type,
                            notify_at_utc=notify_at_utc,
                            source_text=source_text,
                            aim_entity_name=title,
                        )
                        return {"aim": result, "reminder": {"reminder_id": reminder_id, "schedule_type": schedule_type}}
            except Exception as e:
                logger.warning("reminder_create_failed error=%s", e)
        return result
    return await _mcp_tools_call(mcp_name, dict(args))


def _fc_args(fc: Any) -> dict[str, Any]:
    args = getattr(fc, "args", None)
    if isinstance(args, dict):
        return args
    args = getattr(fc, "arguments", None)
    if isinstance(args, dict):
        return args
    # Fallback: try model_dump if present
    try:
        dumped = fc.model_dump()  # type: ignore[attr-defined]
        for k in ("args", "arguments"):
            if isinstance(dumped.get(k), dict):
                return dumped[k]
    except Exception:
        pass
    return {}


async def _ws_to_gemini_loop(ws: WebSocket, session: Any) -> None:
    audio_frames = 0
    while True:
        msg = await ws.receive_json()
        msg_type = msg.get("type")

        # Session control messages (handled locally, never forwarded to Gemini)
        if msg_type == "get_active_trip":
            session_id = getattr(ws.state, "session_id", None)
            if not session_id:
                await ws.send_json({"type": "active_trip", "active_trip_id": None, "active_trip_name": None})
                continue
            state = _get_session_state(str(session_id))
            await ws.send_json({"type": "active_trip", **state})
            continue

        if msg_type == "set_active_trip":
            session_id = getattr(ws.state, "session_id", None)
            active_trip_id = msg.get("active_trip_id")
            active_trip_name = msg.get("active_trip_name")
            if not session_id:
                await ws.send_json({"type": "error", "message": "missing_session_id"})
                continue
            _set_session_state(
                str(session_id),
                str(active_trip_id) if active_trip_id is not None else None,
                str(active_trip_name) if active_trip_name is not None else None,
            )
            state = _get_session_state(str(session_id))
            await ws.send_json({"type": "active_trip", **state})
            continue

        if msg_type == "audio":
            data_b64 = str(msg.get("data") or "")
            mime_type = str(msg.get("mimeType") or "audio/pcm;rate=16000")
            if not data_b64:
                continue
            audio_bytes = base64.b64decode(data_b64)
            await session.send_realtime_input(audio=types.Blob(data=audio_bytes, mime_type=mime_type))
            audio_frames += 1
            if audio_frames % 50 == 0:
                logger.info("forwarded_audio_frames=%s", audio_frames)
            continue

        if msg_type == "text":
            text = str(msg.get("text") or "")
            if not text:
                continue
            handled = await _dispatch_sub_agents(ws, text)
            if handled:
                continue
            await session.send_client_content(turns={"parts": [{"text": text}]}, turn_complete=True)
            continue

        if msg_type == "audio_stream_end":
            await session.send_realtime_input(audio_stream_end=True)
            continue

        if msg_type == "close":
            return


def _extract_audio_b64(server_msg: Any) -> Optional[str]:
    try:
        server_content = getattr(server_msg, "server_content", None)
        if not server_content:
            return None
        model_turn = getattr(server_content, "model_turn", None)
        if not model_turn:
            return None
        parts = getattr(model_turn, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if not inline_data:
                continue
            data = getattr(inline_data, "data", None)
            if not data:
                continue
            if isinstance(data, (bytes, bytearray)):
                return base64.b64encode(bytes(data)).decode("ascii")
            if isinstance(data, str):
                return data
            try:
                as_bytes = bytes(data)
                return base64.b64encode(as_bytes).decode("ascii")
            except Exception:
                return str(data)
    except Exception:
        return None
    return None


async def _gemini_to_ws_loop(ws: WebSocket, session: Any) -> None:
    audio_out_frames = 0
    logged_shape = False
    logged_server_content_shape = False
    while True:
        async for server_msg in session.receive():
            tool_call = getattr(server_msg, "tool_call", None)
            if tool_call is not None:
                function_calls = getattr(tool_call, "function_calls", None) or []
                logger.info("gemini_tool_call count=%s", len(function_calls))
                function_responses: list[Any] = []
                for fc in function_calls:
                    fc_id = getattr(fc, "id", None)
                    fc_name = str(getattr(fc, "name", "") or "")
                    fc_args = _fc_args(fc)
                    logger.info("gemini_tool_call_item name=%s args_keys=%s", fc_name, list(fc_args.keys()))
                    try:
                        session_id = getattr(ws.state, "session_id", None)
                        if fc_name in MCP_TOOL_MAP or fc_name in ("pending_list", "pending_confirm", "pending_cancel"):
                            result = await _handle_mcp_tool_call(session_id, fc_name, fc_args)
                        else:
                            raise HTTPException(status_code=400, detail={"unknown_tool": fc_name})
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc_id,
                                name=fc_name,
                                response={"ok": True, "result": result},
                            )
                        )
                    except HTTPException as e:
                        logger.info("gemini_tool_call_error name=%s status_code=%s", fc_name, e.status_code)
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc_id,
                                name=fc_name,
                                response={"ok": False, "error": e.detail, "status_code": e.status_code},
                            )
                        )
                    except Exception as e:
                        logger.info("gemini_tool_call_exception name=%s error=%s", fc_name, str(e))
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc_id,
                                name=fc_name,
                                response={"ok": False, "error": str(e)},
                            )
                        )

                if function_responses:
                    await session.send_tool_response(function_responses=function_responses)
                continue

            transcription = getattr(server_msg, "transcription", None)
            if transcription is not None:
                text = getattr(transcription, "text", None)
                if text:
                    await ws.send_json({"type": "transcript", "text": str(text)})
                    continue
            elif not logged_shape:
                # One-time debug to understand server message fields.
                try:
                    keys = list(getattr(server_msg, "__dict__", {}).keys())
                    logger.info("live_msg_fields=%s", keys)
                except Exception:
                    logger.info("live_msg_type=%s", type(server_msg))
                logged_shape = True

            server_content = getattr(server_msg, "server_content", None)
            if server_content is not None:
                if not logged_server_content_shape:
                    try:
                        keys = list(getattr(server_content, "__dict__", {}).keys())
                        logger.info("live_server_content_fields=%s", keys)
                    except Exception:
                        logger.info("live_server_content_type=%s", type(server_content))
                    logged_server_content_shape = True

                input_tr = getattr(server_content, "input_transcription", None)
                if input_tr is not None:
                    text = getattr(input_tr, "text", None)
                    if text:
                        await ws.send_json({"type": "transcript", "text": str(text), "source": "input"})
                        continue

                output_tr = getattr(server_content, "output_transcription", None)
                if output_tr is not None:
                    text = getattr(output_tr, "text", None)
                    if text:
                        await ws.send_json({"type": "transcript", "text": str(text), "source": "output"})
                        continue

                model_turn = getattr(server_content, "model_turn", None)
                if model_turn is not None:
                    parts = getattr(model_turn, "parts", None) or []
                    for part in parts:
                        part_text = getattr(part, "text", None)
                        if part_text:
                            await ws.send_json({"type": "text", "text": str(part_text)})
                            break

            audio_b64 = _extract_audio_b64(server_msg)
            if audio_b64:
                await ws.send_json({"type": "audio", "data": audio_b64, "sampleRate": 24000})
                audio_out_frames += 1
                if audio_out_frames % 10 == 0:
                    logger.info("sent_audio_frames=%s", audio_out_frames)
                continue

            # Send text if present (useful for debugging / future UI)
            text = getattr(server_msg, "text", None)
            if text:
                await ws.send_json({"type": "text", "text": str(text)})


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()

    user_id = DEFAULT_USER_ID
    _ws_by_user.setdefault(user_id, set()).add(ws)

    # Sticky session support: the frontend provides ?session_id=... so we can persist
    # per-session state (e.g., active trip) across reconnects.
    session_id = str(ws.query_params.get("session_id") or "").strip() or None
    ws.state.session_id = session_id
    if session_id:
        try:
            _init_session_db()
            state = _get_session_state(session_id)
            await ws.send_json({"type": "active_trip", **state})
        except Exception as e:
            logger.warning("session_db_init_failed error=%s", e)

    try:
        api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("Missing required env var: API_KEY (or GEMINI_API_KEY)")
        client = genai.Client(api_key=api_key)
        config = {
            "response_modalities": ["AUDIO"],
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "tools": [
                {"function_declarations": _mcp_tool_declarations()},
            ],
        }

        logger.info("gemini_live_connect model=%s", MODEL)
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            await ws.send_json({"type": "state", "state": "connected"})

            to_gemini = asyncio.create_task(_ws_to_gemini_loop(ws, session))
            to_ws = asyncio.create_task(_gemini_to_ws_loop(ws, session))

            done, pending = await asyncio.wait(
                [to_gemini, to_ws],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                _ = task.result()

    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
        return
    finally:
        s = _ws_by_user.get(user_id)
        if s is not None:
            s.discard(ws)
