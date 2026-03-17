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


def cancel_pending_write(db_path: str, session_id: str, confirmation_id: str) -> bool:
    init_session_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM pending_writes WHERE session_id = ? AND confirmation_id = ?",
            (session_id, confirmation_id),
        )
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
