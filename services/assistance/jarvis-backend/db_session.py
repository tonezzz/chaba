import json
import os
import sqlite3
import time
from typing import Any, Optional


def init_session_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_last_items (
              session_id TEXT NOT NULL,
              slot TEXT NOT NULL,
              kind TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY(session_id, slot)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS website_sources (
              source_id TEXT PRIMARY KEY,
              provider TEXT NOT NULL,
              root_url TEXT NOT NULL,
              name TEXT,
              config_json TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS website_source_cache (
              source_id TEXT PRIMARY KEY,
              content_json TEXT NOT NULL,
              updated_at INTEGER NOT NULL
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
            CREATE TABLE IF NOT EXISTS news_usage_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS google_tasks_undo (
              undo_id TEXT PRIMARY KEY,
              created_at INTEGER NOT NULL,
              action TEXT NOT NULL,
              tasklist_id TEXT,
              task_id TEXT,
              before_json TEXT,
              after_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS google_calendar_undo (
              undo_id TEXT PRIMARY KEY,
              created_at INTEGER NOT NULL,
              action TEXT NOT NULL,
              event_id TEXT,
              before_json TEXT,
              after_json TEXT
            )
            """
        )


def create_pending_write(db_path: str, session_id: str, action: str, payload: Any) -> str:
    init_session_db(db_path)
    confirmation_id = f"pw_{int(time.time())}_{os.urandom(6).hex()}"
    created_at = int(time.time())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO pending_writes(confirmation_id, session_id, action, payload_json, created_at) VALUES(?, ?, ?, ?, ?)",
            (confirmation_id, session_id, action, payload_json, created_at),
        )
        conn.commit()
    return confirmation_id


def website_sources_list(db_path: str, *, provider: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    init_session_db(db_path)
    try:
        lim = int(limit)
    except Exception:
        lim = 200
    lim = max(1, min(lim, 2000))
    prov = str(provider or "").strip().lower()
    sql = "SELECT source_id, provider, root_url, name, config_json, created_at, updated_at FROM website_sources"
    params: tuple[Any, ...] = ()
    if prov:
        sql += " WHERE lower(provider) = ?"
        params = (prov,)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params = params + (lim,)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(sql, params)
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for source_id, provider2, root_url, name, config_json, created_at, updated_at in rows:
        try:
            cfg = json.loads(config_json)
        except Exception:
            cfg = config_json
        out.append(
            {
                "source_id": str(source_id or ""),
                "provider": str(provider2 or ""),
                "root_url": str(root_url or ""),
                "name": str(name or "").strip() or None,
                "config": cfg,
                "created_at": int(created_at or 0),
                "updated_at": int(updated_at or 0),
            }
        )
    return out


def website_source_upsert(
    db_path: str,
    *,
    source_id: str,
    provider: str,
    root_url: str,
    name: str | None,
    config: Any,
) -> dict[str, Any]:
    init_session_db(db_path)
    sid = str(source_id or "").strip()
    prov = str(provider or "").strip()
    url = str(root_url or "").strip()
    if not sid or not prov or not url:
        raise ValueError("missing_required")
    now_ts = int(time.time())
    config_json = json.dumps(config if config is not None else {}, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO website_sources(source_id, provider, root_url, name, config_json, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              provider=excluded.provider,
              root_url=excluded.root_url,
              name=excluded.name,
              config_json=excluded.config_json,
              updated_at=excluded.updated_at
            """.strip(),
            (sid, prov, url, (str(name).strip() if name is not None and str(name).strip() else None), config_json, now_ts, now_ts),
        )
        conn.commit()
    return {"ok": True, "source_id": sid, "provider": prov, "root_url": url}


def website_source_cache_set(db_path: str, *, source_id: str, content: Any) -> None:
    init_session_db(db_path)
    sid = str(source_id or "").strip()
    if not sid:
        return
    now_ts = int(time.time())
    content_json = json.dumps(content if content is not None else {}, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO website_source_cache(source_id, content_json, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              content_json=excluded.content_json,
              updated_at=excluded.updated_at
            """.strip(),
            (sid, content_json, now_ts),
        )
        conn.commit()


def website_source_cache_get(db_path: str, *, source_id: str) -> Optional[dict[str, Any]]:
    init_session_db(db_path)
    sid = str(source_id or "").strip()
    if not sid:
        return None
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT content_json, updated_at FROM website_source_cache WHERE source_id = ? LIMIT 1",
            (sid,),
        )
        row = cur.fetchone()
    if not row:
        return None
    content_json, updated_at = row
    try:
        content = json.loads(content_json)
    except Exception:
        content = content_json
    return {"source_id": sid, "content": content, "updated_at": int(updated_at or 0)}


def record_news_usage_event(db_path: str, session_id: str, event_type: str, payload: Any) -> bool:
    init_session_db(db_path)
    sid = str(session_id or "").strip()
    et = str(event_type or "").strip()
    if not sid or not et:
        return False
    created_at = int(time.time())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO news_usage_events(session_id, event_type, payload_json, created_at) VALUES(?, ?, ?, ?)",
            (sid, et, payload_json, created_at),
        )
        conn.commit()
    return True


def list_news_usage_events(db_path: str, session_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    init_session_db(db_path)
    sid = str(session_id or "").strip()
    if not sid:
        return []
    try:
        lim = int(limit)
    except Exception:
        lim = 200
    lim = max(1, min(lim, 2000))
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT id, event_type, payload_json, created_at FROM news_usage_events WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (sid, lim),
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for row_id, event_type, payload_json, created_at in rows:
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = payload_json
        out.append(
            {
                "id": int(row_id or 0),
                "event_type": str(event_type or ""),
                "payload": payload,
                "created_at": int(created_at or 0),
            }
        )
    return out


def list_pending_writes(db_path: str, session_id: str) -> list[dict[str, Any]]:
    init_session_db(db_path)
    with sqlite3.connect(db_path) as conn:
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


def get_pending_write(db_path: str, session_id: str, confirmation_id: str) -> Optional[dict[str, Any]]:
    init_session_db(db_path)
    sid = str(session_id or "").strip()
    cid = str(confirmation_id or "").strip()
    if not sid or not cid:
        return None
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT action, payload_json, created_at FROM pending_writes WHERE session_id = ? AND confirmation_id = ?",
            (sid, cid),
        )
        row = cur.fetchone()
    if not row:
        return None
    action, payload_json, created_at = row
    try:
        payload = json.loads(payload_json)
    except Exception:
        payload = payload_json
    return {"confirmation_id": cid, "action": action, "payload": payload, "created_at": int(created_at or 0)}


def get_pending_write_any_session(db_path: str, confirmation_id: str) -> Optional[dict[str, Any]]:
    init_session_db(db_path)
    cid = str(confirmation_id or "").strip()
    if not cid:
        return None
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT session_id, action, payload_json, created_at FROM pending_writes WHERE confirmation_id = ?",
            (cid,),
        )
        row = cur.fetchone()
    if not row:
        return None
    session_id, action, payload_json, created_at = row
    try:
        payload = json.loads(payload_json)
    except Exception:
        payload = payload_json
    return {
        "confirmation_id": cid,
        "session_id": str(session_id or "").strip() or None,
        "action": action,
        "payload": payload,
        "created_at": int(created_at or 0),
    }


def pop_pending_write(db_path: str, session_id: str, confirmation_id: str) -> Optional[dict[str, Any]]:
    init_session_db(db_path)
    with sqlite3.connect(db_path) as conn:
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


def pop_pending_write_any_session(db_path: str, confirmation_id: str) -> Optional[dict[str, Any]]:
    init_session_db(db_path)
    cid = str(confirmation_id or "").strip()
    if not cid:
        return None
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT session_id, action, payload_json, created_at FROM pending_writes WHERE confirmation_id = ?",
            (cid,),
        )
        row = cur.fetchone()
        if not row:
            return None
        session_id, action, payload_json, created_at = row
        conn.execute("DELETE FROM pending_writes WHERE confirmation_id = ?", (cid,))
        conn.commit()
    try:
        payload = json.loads(payload_json)
    except Exception:
        payload = payload_json
    return {
        "confirmation_id": cid,
        "session_id": str(session_id or "").strip() or None,
        "action": action,
        "payload": payload,
        "created_at": int(created_at or 0),
    }


def cancel_pending_write(db_path: str, session_id: str, confirmation_id: str) -> bool:
    init_session_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM pending_writes WHERE session_id = ? AND confirmation_id = ?",
            (session_id, confirmation_id),
        )
        conn.commit()
        return (cur.rowcount or 0) > 0


def cancel_pending_write_any_session(db_path: str, confirmation_id: str) -> bool:
    init_session_db(db_path)
    cid = str(confirmation_id or "").strip()
    if not cid:
        return False
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM pending_writes WHERE confirmation_id = ?", (cid,))
        conn.commit()
        return (cur.rowcount or 0) > 0


def reassign_pending_write(db_path: str, confirmation_id: str, new_session_id: str) -> bool:
    init_session_db(db_path)
    cid = str(confirmation_id or "").strip()
    sid = str(new_session_id or "").strip()
    if not cid or not sid:
        return False
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("UPDATE pending_writes SET session_id = ? WHERE confirmation_id = ?", (sid, cid))
        conn.commit()
        return (cur.rowcount or 0) > 0


def set_session_last_item(db_path: str, session_id: str, slot: str, kind: str, payload: dict[str, Any]) -> None:
    init_session_db(db_path)
    sid = str(session_id or "").strip()
    if not sid:
        return
    slot_norm = str(slot or "").strip().lower()
    if slot_norm not in ("last_created", "last_modified"):
        return
    kind_norm = str(kind or "").strip().lower()
    if kind_norm not in ("task", "calendar_event"):
        return
    now = int(time.time())
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO session_last_items(session_id, slot, kind, payload_json, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(session_id, slot) DO UPDATE SET
              kind=excluded.kind,
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (sid, slot_norm, kind_norm, payload_json, now),
        )
        conn.commit()


def get_session_last_item(db_path: str, session_id: str, slot: str) -> Optional[dict[str, Any]]:
    init_session_db(db_path)
    sid = str(session_id or "").strip()
    if not sid:
        return None
    slot_norm = str(slot or "").strip().lower()
    if slot_norm not in ("last_created", "last_modified"):
        return None
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT kind, payload_json, updated_at FROM session_last_items WHERE session_id = ? AND slot = ?",
            (sid, slot_norm),
        )
        row = cur.fetchone()
    if not row:
        return None
    kind, payload_json, updated_at = row
    payload: Any
    try:
        payload = json.loads(payload_json)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"raw": payload}
    out: dict[str, Any] = {"slot": slot_norm, "kind": kind, "updated_at": int(updated_at or 0)}
    out.update(payload)
    return out


def google_tasks_undo_log(db_path: str, action: str, tasklist_id: Optional[str], task_id: Optional[str], before: Any, after: Any) -> str:
    init_session_db(db_path)
    undo_id = f"gtu_{int(time.time())}_{os.urandom(6).hex()}"
    created_at = int(time.time())
    before_json = json.dumps(before, ensure_ascii=False) if before is not None else ""
    after_json = json.dumps(after, ensure_ascii=False) if after is not None else ""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO google_tasks_undo(undo_id, created_at, action, tasklist_id, task_id, before_json, after_json) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (undo_id, created_at, action, tasklist_id, task_id, before_json, after_json),
        )
        conn.commit()
    return undo_id


def google_tasks_undo_list(db_path: str, limit: int) -> list[dict[str, Any]]:
    init_session_db(db_path)
    lim = max(1, min(int(limit or 10), 100))
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT undo_id, created_at, action, tasklist_id, task_id, before_json, after_json FROM google_tasks_undo ORDER BY created_at DESC LIMIT ?",
            (lim,),
        )
        rows = cur.fetchall() or []

    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, (list, tuple)) or len(r) < 7:
            continue
        before_obj = None
        after_obj = None
        try:
            before_obj = json.loads(r[5]) if r[5] else None
        except Exception:
            before_obj = None
        try:
            after_obj = json.loads(r[6]) if r[6] else None
        except Exception:
            after_obj = None
        out.append(
            {
                "undo_id": r[0],
                "created_at": int(r[1] or 0),
                "action": r[2],
                "tasklist_id": r[3],
                "task_id": r[4],
                "before": before_obj,
                "after": after_obj,
            }
        )
    return out


def google_tasks_undo_pop_last(db_path: str, n: int) -> list[dict[str, Any]]:
    init_session_db(db_path)
    nn = max(1, min(int(n or 1), 50))
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT undo_id, created_at, action, tasklist_id, task_id, before_json, after_json FROM google_tasks_undo ORDER BY created_at DESC LIMIT ?",
            (nn,),
        )
        rows = cur.fetchall() or []
        ids = [r[0] for r in rows if isinstance(r, (list, tuple)) and r and r[0]]
        if ids:
            conn.executemany("DELETE FROM google_tasks_undo WHERE undo_id = ?", [(i,) for i in ids])
        conn.commit()

    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, (list, tuple)) or len(r) < 7:
            continue
        before_obj = None
        after_obj = None
        try:
            before_obj = json.loads(r[5]) if r[5] else None
        except Exception:
            before_obj = None
        try:
            after_obj = json.loads(r[6]) if r[6] else None
        except Exception:
            after_obj = None
        out.append(
            {
                "undo_id": r[0],
                "created_at": int(r[1] or 0),
                "action": r[2],
                "tasklist_id": r[3],
                "task_id": r[4],
                "before": before_obj,
                "after": after_obj,
            }
        )
    return out


def google_calendar_undo_log(db_path: str, action: str, event_id: Optional[str], before: Any, after: Any) -> str:
    init_session_db(db_path)
    undo_id = f"gcu_{int(time.time())}_{os.urandom(6).hex()}"
    created_at = int(time.time())
    before_json = json.dumps(before, ensure_ascii=False) if before is not None else ""
    after_json = json.dumps(after, ensure_ascii=False) if after is not None else ""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO google_calendar_undo(undo_id, created_at, action, event_id, before_json, after_json) VALUES(?, ?, ?, ?, ?, ?)",
            (undo_id, created_at, action, event_id, before_json, after_json),
        )
        conn.commit()
    return undo_id


def google_calendar_undo_list(db_path: str, limit: int) -> list[dict[str, Any]]:
    init_session_db(db_path)
    lim = max(1, min(int(limit or 10), 100))
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT undo_id, created_at, action, event_id, before_json, after_json FROM google_calendar_undo ORDER BY created_at DESC LIMIT ?",
            (lim,),
        )
        rows = cur.fetchall() or []

    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, (list, tuple)) or len(r) < 6:
            continue
        before_obj = None
        after_obj = None
        try:
            before_obj = json.loads(r[4]) if r[4] else None
        except Exception:
            before_obj = None
        try:
            after_obj = json.loads(r[5]) if r[5] else None
        except Exception:
            after_obj = None
        out.append(
            {
                "undo_id": r[0],
                "created_at": int(r[1] or 0),
                "action": r[2],
                "event_id": r[3],
                "before": before_obj,
                "after": after_obj,
            }
        )
    return out


def google_calendar_undo_pop_last(db_path: str, n: int) -> list[dict[str, Any]]:
    init_session_db(db_path)
    nn = max(1, min(int(n or 1), 50))
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT undo_id, created_at, action, event_id, before_json, after_json FROM google_calendar_undo ORDER BY created_at DESC LIMIT ?",
            (nn,),
        )
        rows = cur.fetchall() or []
        ids = [r[0] for r in rows if isinstance(r, (list, tuple)) and r and r[0]]
        if ids:
            conn.executemany("DELETE FROM google_calendar_undo WHERE undo_id = ?", [(i,) for i in ids])
        conn.commit()

    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, (list, tuple)) or len(r) < 6:
            continue
        before_obj = None
        after_obj = None
        try:
            before_obj = json.loads(r[4]) if r[4] else None
        except Exception:
            before_obj = None
        try:
            after_obj = json.loads(r[5]) if r[5] else None
        except Exception:
            after_obj = None
        out.append(
            {
                "undo_id": r[0],
                "created_at": int(r[1] or 0),
                "action": r[2],
                "event_id": r[3],
                "before": before_obj,
                "after": after_obj,
            }
        )
    return out
