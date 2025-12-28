import asyncio
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from html import escape
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import AliasChoices, BaseModel, Field


def _utc_ts() -> int:
    return int(time.time())


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _ensure_dir_for_file(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _get_db_path() -> str:
    return os.getenv("MCP_TASK_DB_PATH", "/data/sqlite/mcp-task.sqlite")


def _get_servers() -> Dict[str, str]:
    raw = os.getenv("MCP_TASK_SERVERS", "[]")
    try:
        items = json.loads(raw)
        out: Dict[str, str] = {}
        for it in items:
            name = str(it.get("name", "")).strip()
            url = str(it.get("url", "")).strip()
            if name and url:
                out[name] = url.rstrip("/")
        return out
    except Exception:
        return {}


def _append_conversation_message(
    conversation_id: str,
    role: str,
    content: str,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    conv = _conversation_row(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    now = _utc_ts()
    message_id = str(uuid.uuid4())
    meta_json = _json_dumps(meta) if isinstance(meta, dict) else None
    _conn.execute(
        "INSERT INTO conversation_messages (message_id, conversation_id, role, content, created_at, meta_json) VALUES (?, ?, ?, ?, ?, ?)",
        (message_id, conversation_id, str(role), str(content), now, meta_json),
    )
    _conn.execute(
        "UPDATE conversations SET updated_at=? WHERE conversation_id=?",
        (now, conversation_id),
    )
    _conn.commit()
    return message_id


def _conversation_messages_as_llm_messages(conversation_id: str, limit: int = 200) -> List[Dict[str, str]]:
    rows = _conversation_message_rows(conversation_id=conversation_id, limit=limit, offset=0)
    out: List[Dict[str, str]] = []
    for r in rows:
        role = str(r["role"] or "user").strip().lower()
        if role not in ("user", "assistant", "system"):
            role = "user"
        out.append({"role": role, "content": str(r["content"] or "")})
    return out


def _extract_action_json(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidate = raw[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None
    return None


async def _autopilot_step(conversation_id: str, dry_run: bool = False) -> Dict[str, Any]:
    conv = _conversation_row(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    workflows: Any
    try:
        workflows = await _invoke_remote("mcp-devops", "list_workflows", {})
    except Exception as e:
        workflows = {"ok": False, "error": str(e)}

    system_prompt = (
        "You are an operations autopilot. You must respond with ONLY valid JSON. "
        "Choose at most one action. Allowed action: call mcp-devops.run_workflow. "
        "Schema: {\"action\":{\"server\":\"mcp-devops\",\"tool\":\"run_workflow\",\"args\":{\"workflow_id\":string,\"dry_run\":boolean?}}}. "
        "If you cannot decide safely, respond with {\"action\":null,\"reason\":string}. "
        "Available workflows are provided in the next message."
    )

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": "Workflows:\n" + json.dumps(workflows, ensure_ascii=False)},
    ]
    messages.extend(_conversation_messages_as_llm_messages(conversation_id))

    llm_res = await _invoke_remote(
        "mcp-glama",
        "chat_completion",
        {
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 600,
        },
    )

    assistant_text = ""
    if isinstance(llm_res, dict):
        assistant_text = str(llm_res.get("response") or "")
    _append_conversation_message(
        conversation_id,
        role="assistant",
        content=assistant_text or json.dumps(llm_res, ensure_ascii=False),
        meta={"source": "mcp-glama"},
    )

    action_obj = _extract_action_json(assistant_text)
    if not isinstance(action_obj, dict):
        return {"ok": False, "error": "assistant_response_not_json", "raw": llm_res}

    action = action_obj.get("action")
    if not action:
        return {"ok": True, "action": None, "reason": action_obj.get("reason"), "raw": action_obj}

    if not isinstance(action, dict):
        return {"ok": False, "error": "invalid_action", "raw": action_obj}

    server = str(action.get("server") or "")
    tool = str(action.get("tool") or "")
    args = action.get("args") or {}

    if server != "mcp-devops" or tool != "run_workflow":
        return {"ok": False, "error": "disallowed_action", "raw": action_obj}

    if not isinstance(args, dict) or not str(args.get("workflow_id") or "").strip():
        return {"ok": False, "error": "missing_workflow_id", "raw": action_obj}

    if dry_run and "dry_run" not in args:
        args = dict(args)
        args["dry_run"] = True

    _append_conversation_message(
        conversation_id,
        role="tool",
        content=json.dumps({"server": server, "tool": tool, "args": args}, ensure_ascii=False, indent=2),
        meta={"type": "tool_call"},
    )

    try:
        tool_result = await _invoke_remote(server, tool, args)
        _append_conversation_message(
            conversation_id,
            role="tool",
            content=json.dumps(tool_result, ensure_ascii=False, indent=2),
            meta={"type": "tool_result"},
        )
        return {"ok": True, "action": {"server": server, "tool": tool, "args": args}, "result": tool_result}
    except Exception as e:
        _append_conversation_message(
            conversation_id,
            role="tool",
            content=str(e),
            meta={"type": "tool_error"},
        )
        return {"ok": False, "action": {"server": server, "tool": tool, "args": args}, "error": str(e)}


def _db() -> sqlite3.Connection:
    db_path = _get_db_path()
    _ensure_dir_for_file(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return [r["name"] for r in cur.fetchall()]
    except Exception:
        return []


def _init_db(conn: sqlite3.Connection) -> None:
    # Legacy schema migration (older mcp-task versions used tasks.id and runs.job_id/result_json)
    # Convert in-place to the current schema so the rest of the service can operate normally.
    task_cols = _table_columns(conn, "tasks")
    run_cols = _table_columns(conn, "runs")
    if task_cols and "task_id" not in task_cols and "id" in task_cols:
        # Rename the legacy tables out of the way, then create the new tables and copy data over.
        # This avoids subtle issues with DROP/ALTER ordering and lets us retry safely.
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE tasks RENAME TO tasks_old")
        if run_cols:
            conn.execute("ALTER TABLE runs RENAME TO runs_old")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                approved_at INTEGER,
                approved_by TEXT,
                spec_json TEXT NOT NULL,
                last_error TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO tasks (task_id, title, status, created_at, approved_at, approved_by, spec_json, last_error)
            SELECT id, title, status, created_at, approved_at, approved_by, spec_json, NULL FROM tasks_old
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                finished_at INTEGER,
                report_json TEXT,
                error TEXT,
                FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            )
            """
        )

        if run_cols and "job_id" in run_cols:
            error_expr = "error" if "error" in run_cols else ("error_message" if "error_message" in run_cols else "NULL")
            finished_expr = "finished_at" if "finished_at" in run_cols else ("ended_at" if "ended_at" in run_cols else "NULL")
            report_expr = "report_json" if "report_json" in run_cols else ("result_json" if "result_json" in run_cols else "NULL")
            started_expr = "created_at" if "created_at" in run_cols else ("started_at" if "started_at" in run_cols else "NULL")
            conn.execute(
                f"""
                INSERT OR IGNORE INTO runs (run_id, task_id, status, created_at, finished_at, report_json, error)
                SELECT id, job_id, status, {started_expr}, {finished_expr}, {report_expr}, {error_expr} FROM runs_old
                """
            )

        conn.execute("DROP TABLE IF EXISTS runs_old")
        conn.execute("DROP TABLE IF EXISTS tasks_old")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            approved_at INTEGER,
            approved_by TEXT,
            spec_json TEXT NOT NULL,
            last_error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            finished_at INTEGER,
            report_json TEXT,
            error TEXT,
            FOREIGN KEY(task_id) REFERENCES tasks(task_id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            meta_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            meta_json TEXT,
            FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_id_created_at
        ON conversation_messages(conversation_id, created_at)
        """
    )
    conn.commit()


class ToolCall(BaseModel):
    server: str
    tool: str
    args: Dict[str, Any] = Field(
        default_factory=dict, validation_alias=AliasChoices("args", "arguments")
    )


class ToolCallPatch(BaseModel):
    server: Optional[str] = None
    tool: Optional[str] = None
    args: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias=AliasChoices("args", "arguments")
    )


class CreateTaskArgs(BaseModel):
    title: str
    call: ToolCall


class UpdateTaskArgs(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))
    title: Optional[str] = None
    call: Optional[ToolCallPatch] = None


class ApproveTaskArgs(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))
    approved_by: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("approved_by", "approvedBy")
    )


class GetTaskArgs(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))


class GetTaskReportArgs(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))


class ListTasksArgs(BaseModel):
    status: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class CreateConversationArgs(BaseModel):
    title: Optional[str] = None
    source: str = Field(default="chat")
    meta: Optional[Dict[str, Any]] = None


class AppendConversationMessageArgs(BaseModel):
    conversation_id: str = Field(validation_alias=AliasChoices("conversation_id", "conversationId"))
    role: str
    content: str
    meta: Optional[Dict[str, Any]] = None


class GetConversationArgs(BaseModel):
    conversation_id: str = Field(validation_alias=AliasChoices("conversation_id", "conversationId"))


class ListConversationsArgs(BaseModel):
    source: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ListRunsArgs(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


@dataclass
class SseSession:
    session_id: str
    queue: "asyncio.Queue[Dict[str, Any]]"
    created_at: int


app = FastAPI(title="mcp-task", version="0.1.0")

_conn = _db()
_init_db(_conn)

_sessions: Dict[str, SseSession] = {}


@app.get("/health")
def health() -> Dict[str, Any]:
    try:
        _conn.execute("SELECT 1")
        return {"ok": True, "service": "mcp-task"}
    except Exception as e:
        return {"ok": False, "service": "mcp-task", "error": str(e)}


def _fmt_ts(ts: Optional[int]) -> str:
    if ts is None:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(ts)))
    except Exception:
        return str(ts)


def _html_page(title: str, body: str) -> HTMLResponse:
    html = (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'/>"
        f"<title>{escape(title)}</title>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<style>"
        "body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial;max-width:1100px;margin:24px auto;padding:0 16px;}"
        "a{color:#2563eb;text-decoration:none} a:hover{text-decoration:underline}"
        "h1{font-size:20px;margin:0 0 16px 0} h2{font-size:16px;margin:20px 0 10px 0}"
        ".muted{color:#6b7280}"
        "table{width:100%;border-collapse:collapse;font-size:13px}"
        "th,td{padding:8px 10px;border-bottom:1px solid #e5e7eb;vertical-align:top}"
        "th{text-align:left;color:#374151;font-weight:600}"
        "code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}"
        "pre{background:#0b1020;color:#e5e7eb;padding:12px;border-radius:8px;overflow:auto;font-size:12px}"
        ".pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#f3f4f6;color:#111827}"
        ".row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:0 0 12px 0}"
        "</style></head><body>"
        f"<div class='row'><a href='/control'>Control</a><span class='muted'>/</span><a href='/chat'>Chat</a><span class='muted'>/</span><a href='/agents'>Agents</a><span class='muted'>/</span><span class='muted'>{escape(title)}</span></div>"
        f"<h1>{escape(title)}</h1>"
        f"{body}"
        "</body></html>"
    )
    return HTMLResponse(html)


def _conversation_row(conversation_id: str) -> Optional[sqlite3.Row]:
    cur = _conn.execute(
        "SELECT * FROM conversations WHERE conversation_id = ?",
        (conversation_id,),
    )
    return cur.fetchone()


def _conversation_message_rows(conversation_id: str, limit: int, offset: int) -> List[sqlite3.Row]:
    cur = _conn.execute(
        "SELECT * FROM conversation_messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?",
        (conversation_id, limit, offset),
    )
    return list(cur.fetchall())


def _list_conversation_rows(source: Optional[str], limit: int, offset: int) -> List[sqlite3.Row]:
    if source:
        cur = _conn.execute(
            "SELECT * FROM conversations WHERE source = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (source, limit, offset),
        )
    else:
        cur = _conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    return list(cur.fetchall())


def _conversation_to_dict(row: sqlite3.Row, messages: Optional[List[sqlite3.Row]] = None) -> Dict[str, Any]:
    out = dict(row)
    out["meta"] = json.loads(out["meta_json"]) if out.get("meta_json") else None
    out.pop("meta_json", None)
    if messages is not None:
        out_messages: List[Dict[str, Any]] = []
        for m in messages:
            md = dict(m)
            md["meta"] = json.loads(md["meta_json"]) if md.get("meta_json") else None
            md.pop("meta_json", None)
            out_messages.append(md)
        out["messages"] = out_messages
    return out


def _run_row(run_id: str) -> Optional[sqlite3.Row]:
    cur = _conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    return cur.fetchone()


def _control_task_rows(status: Optional[str], limit: int, offset: int) -> List[sqlite3.Row]:
    if status:
        cur = _conn.execute(
            "SELECT task_id, title, status, created_at, last_error FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    else:
        cur = _conn.execute(
            "SELECT task_id, title, status, created_at, last_error FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    return list(cur.fetchall())


@app.get("/control")
def control_home(limit: int = 50, offset: int = 0, status: Optional[str] = None) -> HTMLResponse:
    rows = _control_task_rows(status=status, limit=limit, offset=offset)
    filters = (
        "<div class='row'>"
        "<span class='muted'>Filters:</span>"
        "<a class='pill' href='/control'>all</a>"
        "<a class='pill' href='/control?status=pending'>pending</a>"
        "<a class='pill' href='/control?status=approved'>approved</a>"
        "<a class='pill' href='/control?status=completed'>completed</a>"
        "<a class='pill' href='/control?status=failed'>failed</a>"
        "</div>"
    )
    table = [
        "<table><thead><tr>"
        "<th>task</th><th>title</th><th>status</th><th>created</th><th>latest run</th><th>last error</th>"
        "</tr></thead><tbody>"
    ]
    for r in rows:
        task_id = str(r["task_id"]) if "task_id" in r.keys() else str(dict(r).get("task_id", ""))
        latest = _latest_run_row(task_id)
        latest_cell = ""
        if latest is not None:
            latest_cell = (
                f"<a href='/control/run/{escape(latest['run_id'])}'>{escape(latest['run_id'])}</a>"
                f"<div class='muted'>{escape(str(latest['status']))} · {_fmt_ts(latest['created_at'])}</div>"
            )
        last_error = r["last_error"]
        last_error_text = escape(str(last_error)) if last_error else ""
        table.append(
            "<tr>"
            f"<td><a href='/control/task/{escape(task_id)}'>{escape(task_id)}</a></td>"
            f"<td>{escape(r['title'])}</td>"
            f"<td><span class='pill'>{escape(r['status'])}</span></td>"
            f"<td class='muted'>{escape(_fmt_ts(r['created_at']))}</td>"
            f"<td>{latest_cell}</td>"
            f"<td class='muted'>{last_error_text}</td>"
            "</tr>"
        )
    table.append("</tbody></table>")
    nav = "<div class='row' style='margin-top:14px'>"
    prev_off = max(0, offset - limit)
    next_off = offset + limit
    qs_status = f"&status={escape(status)}" if status else ""
    nav += f"<a class='pill' href='/control?limit={limit}&offset={prev_off}{qs_status}'>Prev</a>"
    nav += f"<a class='pill' href='/control?limit={limit}&offset={next_off}{qs_status}'>Next</a>"
    nav += f"<span class='muted'>limit={limit} offset={offset}</span>"
    nav += "</div>"
    return _html_page("Tasks", filters + "".join(table) + nav)


@app.get("/chat")
def chat_home(limit: int = 50, offset: int = 0, source: Optional[str] = None) -> HTMLResponse:
    rows = _list_conversation_rows(source=source, limit=limit, offset=offset)
    header = (
        "<div class='row'>"
        "<span class='muted'>Conversations:</span>"
        "<a class='pill' href='/chat'>all</a>"
        "<a class='pill' href='/chat?source=chat'>chat</a>"
        "<a class='pill' href='/chat?source=autopilot'>autopilot</a>"
        "<a class='pill' href='/chat?source=agents'>agents</a>"
        "</div>"
        "<h2>New conversation</h2>"
        "<form method='post' action='/chat/create' class='row'>"
        "<input name='title' placeholder='title (optional)' style='flex:1;min-width:240px;padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px'/>"
        "<select name='source' style='padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px'>"
        "<option value='chat'>chat</option>"
        "<option value='autopilot'>autopilot</option>"
        "</select>"
        "<button type='submit' style='padding:8px 12px;border:1px solid #e5e7eb;border-radius:8px;background:#111827;color:#fff'>Create</button>"
        "</form>"
    )
    table = [
        "<h2>History</h2>",
        "<table><thead><tr><th>conversation</th><th>title</th><th>source</th><th>updated</th><th>created</th></tr></thead><tbody>",
    ]
    for r in rows:
        table.append(
            "<tr>"
            f"<td><a href='/chat/{escape(r['conversation_id'])}'>{escape(r['conversation_id'])}</a></td>"
            f"<td>{escape(r['title'])}</td>"
            f"<td><span class='pill'>{escape(r['source'])}</span></td>"
            f"<td class='muted'>{escape(_fmt_ts(r['updated_at']))}</td>"
            f"<td class='muted'>{escape(_fmt_ts(r['created_at']))}</td>"
            "</tr>"
        )
    table.append("</tbody></table>")
    prev_off = max(0, offset - limit)
    next_off = offset + limit
    qs_source = f"&source={escape(source)}" if source else ""
    nav = "<div class='row' style='margin-top:14px'>"
    nav += f"<a class='pill' href='/chat?limit={limit}&offset={prev_off}{qs_source}'>Prev</a>"
    nav += f"<a class='pill' href='/chat?limit={limit}&offset={next_off}{qs_source}'>Next</a>"
    nav += f"<span class='muted'>limit={limit} offset={offset}</span>"
    nav += "</div>"
    return _html_page("Chat", header + "".join(table) + nav)


@app.post("/chat/create")
async def chat_create(request: Request) -> HTMLResponse:
    form = await request.form()
    title = str(form.get("title") or "").strip()
    source = str(form.get("source") or "chat").strip() or "chat"
    now = _utc_ts()
    conversation_id = str(uuid.uuid4())
    title_to_store = title or f"Conversation {conversation_id[:8]}"
    _conn.execute(
        "INSERT INTO conversations (conversation_id, title, source, created_at, updated_at, meta_json) VALUES (?, ?, ?, ?, ?, ?)",
        (conversation_id, title_to_store, source, now, now, None),
    )
    _conn.commit()
    return _html_page("Created", f"<div class='row'><a class='pill' href='/chat/{escape(conversation_id)}'>Open conversation</a></div>")


@app.get("/chat/{conversation_id}")
def chat_view(conversation_id: str, limit: int = 500, offset: int = 0) -> HTMLResponse:
    conv = _conversation_row(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    rows = _conversation_message_rows(conversation_id=conversation_id, limit=limit, offset=offset)
    items: List[str] = []
    items.append(
        "<div class='row'>"
        f"<span class='pill'>{escape(conv['source'])}</span>"
        f"<span class='muted'>created {_fmt_ts(conv['created_at'])}</span>"
        f"<span class='muted'>updated {_fmt_ts(conv['updated_at'])}</span>"
        "</div>"
    )
    items.append("<h2>Append</h2>")
    items.append(
        "<form method='post' action='/chat/" + escape(conversation_id) + "/append'>"
        "<div class='row'>"
        "<select name='role' style='padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px'>"
        "<option value='user'>user</option>"
        "<option value='assistant'>assistant</option>"
        "<option value='system'>system</option>"
        "<option value='tool'>tool</option>"
        "</select>"
        "</div>"
        "<textarea name='content' rows='6' style='width:100%;padding:10px;border:1px solid #e5e7eb;border-radius:8px' placeholder='message...'></textarea>"
        "<div class='row' style='margin-top:10px'>"
        "<button type='submit' style='padding:8px 12px;border:1px solid #e5e7eb;border-radius:8px;background:#111827;color:#fff'>Add message</button>"
        "</div>"
        "</form>"
    )

    items.append("<h2>Transcript</h2>")
    items.append("<table><thead><tr><th>time</th><th>role</th><th>content</th></tr></thead><tbody>")
    for m in rows:
        items.append(
            "<tr>"
            f"<td class='muted' style='white-space:nowrap'>{escape(_fmt_ts(m['created_at']))}</td>"
            f"<td><span class='pill'>{escape(m['role'])}</span></td>"
            f"<td><pre style='margin:0'>{escape(str(m['content'] or ''))}</pre></td>"
            "</tr>"
        )
    items.append("</tbody></table>")
    return _html_page(conv["title"], "".join(items))


@app.post("/chat/{conversation_id}/run")
async def chat_run(conversation_id: str, request: Request) -> HTMLResponse:
    form = await request.form()
    dry_run = str(form.get("dry_run") or "").strip() in ("1", "true", "True")
    try:
        result = await _autopilot_step(conversation_id=conversation_id, dry_run=dry_run)
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    _append_conversation_message(
        conversation_id,
        role="system",
        content=json.dumps({"autopilot": result}, ensure_ascii=False, indent=2),
        meta={"type": "autopilot_step"},
    )
    return chat_view(conversation_id)


@app.post("/chat/{conversation_id}/run.json")
async def chat_run_json(conversation_id: str, req: Request) -> JSONResponse:
    body = await req.json()
    dry_run = bool((body or {}).get("dry_run"))
    result = await _autopilot_step(conversation_id=conversation_id, dry_run=dry_run)
    return JSONResponse(result)


@app.post("/chat/{conversation_id}/append")
async def chat_append(conversation_id: str, request: Request) -> HTMLResponse:
    conv = _conversation_row(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    form = await request.form()
    role = str(form.get("role") or "user").strip() or "user"
    content = str(form.get("content") or "")
    now = _utc_ts()
    message_id = str(uuid.uuid4())
    _conn.execute(
        "INSERT INTO conversation_messages (message_id, conversation_id, role, content, created_at, meta_json) VALUES (?, ?, ?, ?, ?, ?)",
        (message_id, conversation_id, role, content, now, None),
    )
    _conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
        (now, conversation_id),
    )
    _conn.commit()
    return chat_view(conversation_id)


@app.get("/agents")
async def agents_history() -> HTMLResponse:
    body: List[str] = []
    body.append("<div class='muted'>Pulled live via mcp-agents (fetch_sessions / fetch_archives).</div>")
    try:
        sessions = await _invoke_remote("mcp-agents", "fetch_sessions", {})
    except Exception as e:
        sessions = {"ok": False, "error": str(e)}
    try:
        archives = await _invoke_remote("mcp-agents", "fetch_archives", {})
    except Exception as e:
        archives = {"ok": False, "error": str(e)}
    body.append("<h2>Sessions</h2>")
    body.append(f"<pre>{escape(json.dumps(sessions, ensure_ascii=False, indent=2))}</pre>")
    body.append("<h2>Archives</h2>")
    body.append(f"<pre>{escape(json.dumps(archives, ensure_ascii=False, indent=2))}</pre>")
    return _html_page("Agents", "".join(body))


@app.get("/control/task/{task_id}")
def control_task(task_id: str, limit: int = 50, offset: int = 0) -> HTMLResponse:
    task = _task_row(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    spec = json.loads(task["spec_json"]) if task["spec_json"] is not None else None
    spec_pre = f"<h2>Spec</h2><pre>{escape(json.dumps(spec, ensure_ascii=False, indent=2))}</pre>" if spec else ""

    rows = _runs_for_task(task_id=task_id, limit=limit, offset=offset)
    table = [
        "<h2>Runs</h2>",
        "<table><thead><tr>"
        "<th>run</th><th>status</th><th>created</th><th>finished</th><th>error</th><th>report</th>"
        "</tr></thead><tbody>",
    ]
    for r in rows:
        err = r["error"]
        err_text = escape(str(err)) if err else ""
        report_link = f"<a href='/control/run/{escape(r['run_id'])}'>open</a>"
        table.append(
            "<tr>"
            f"<td><a href='/control/run/{escape(r['run_id'])}'>{escape(r['run_id'])}</a></td>"
            f"<td><span class='pill'>{escape(r['status'])}</span></td>"
            f"<td class='muted'>{escape(_fmt_ts(r['created_at']))}</td>"
            f"<td class='muted'>{escape(_fmt_ts(r['finished_at']))}</td>"
            f"<td class='muted'>{err_text}</td>"
            f"<td>{report_link}</td>"
            "</tr>"
        )
    table.append("</tbody></table>")

    nav = "<div class='row' style='margin-top:14px'>"
    prev_off = max(0, offset - limit)
    next_off = offset + limit
    nav += f"<a class='pill' href='/control/task/{escape(task_id)}?limit={limit}&offset={prev_off}'>Prev</a>"
    nav += f"<a class='pill' href='/control/task/{escape(task_id)}?limit={limit}&offset={next_off}'>Next</a>"
    nav += f"<span class='muted'>limit={limit} offset={offset}</span>"
    nav += "</div>"

    header = (
        "<div class='row'>"
        f"<span class='pill'>{escape(task['status'])}</span>"
        f"<span class='muted'>created {_fmt_ts(task['created_at'])}</span>"
        "</div>"
    )
    title = f"Task {task_id}"
    body = header + f"<div><strong>{escape(task['title'])}</strong></div>" + spec_pre + "".join(table) + nav
    return _html_page(title, body)


@app.get("/control/run/{run_id}")
def control_run(run_id: str) -> HTMLResponse:
    run = _run_row(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    report = json.loads(run["report_json"]) if run["report_json"] else None
    report_pre = (
        f"<h2>Report</h2><div class='row'>"
        f"<a class='pill' href='/control/run/{escape(run_id)}/report.json'>report.json</a>"
        "</div>"
        f"<pre>{escape(json.dumps(report, ensure_ascii=False, indent=2))}</pre>"
        if report is not None
        else "<h2>Report</h2><div class='muted'>No report stored</div>"
    )
    err = run["error"]
    err_pre = f"<h2>Error</h2><pre>{escape(str(err))}</pre>" if err else ""

    header = (
        "<div class='row'>"
        f"<a class='pill' href='/control/task/{escape(run['task_id'])}'>task</a>"
        f"<span class='pill'>{escape(run['status'])}</span>"
        f"<span class='muted'>created {_fmt_ts(run['created_at'])}</span>"
        f"<span class='muted'>finished {_fmt_ts(run['finished_at'])}</span>"
        "</div>"
    )
    body = header + report_pre + err_pre
    return _html_page(f"Run {run_id}", body)


@app.get("/control/run/{run_id}/report.json")
def control_run_report_json(run_id: str) -> JSONResponse:
    run = _run_row(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    report = json.loads(run["report_json"]) if run["report_json"] else None
    return JSONResponse({"run_id": run_id, "task_id": run["task_id"], "report": report})


def _tool_list() -> List[Dict[str, Any]]:
    return [
        {
            "name": "create_task",
            "description": "Create a task which, when approved, will invoke a tool on another MCP server.",
            "inputSchema": CreateTaskArgs.model_json_schema(),
        },
        {
            "name": "update_task",
            "description": "Update a pending task's title and/or tool call (server/tool/args).",
            "inputSchema": UpdateTaskArgs.model_json_schema(),
        },
        {
            "name": "approve_task",
            "description": "Approve and execute a task, creating a run and storing its report.",
            "inputSchema": ApproveTaskArgs.model_json_schema(),
        },
        {
            "name": "get_task",
            "description": "Fetch task status and latest run metadata.",
            "inputSchema": GetTaskArgs.model_json_schema(),
        },
        {
            "name": "get_task_report",
            "description": "Fetch the latest run report for a task.",
            "inputSchema": GetTaskReportArgs.model_json_schema(),
        },
        {
            "name": "list_tasks",
            "description": "List tasks (optionally filtered by status) with pagination.",
            "inputSchema": ListTasksArgs.model_json_schema(),
        },
        {
            "name": "list_runs",
            "description": "List runs for a task with pagination.",
            "inputSchema": ListRunsArgs.model_json_schema(),
        },
        {
            "name": "create_conversation",
            "description": "Create a conversation container for chat transcripts and tool timelines.",
            "inputSchema": CreateConversationArgs.model_json_schema(),
        },
        {
            "name": "append_conversation_message",
            "description": "Append a message to a stored conversation transcript.",
            "inputSchema": AppendConversationMessageArgs.model_json_schema(),
        },
        {
            "name": "get_conversation",
            "description": "Fetch a conversation and its messages.",
            "inputSchema": GetConversationArgs.model_json_schema(),
        },
        {
            "name": "list_conversations",
            "description": "List conversations with pagination (optionally filtered by source).",
            "inputSchema": ListConversationsArgs.model_json_schema(),
        },
    ]


@app.get("/tools")
def tools() -> Dict[str, Any]:
    return {"tools": _tool_list()}


@app.get("/.well-known/mcp.json")
def well_known() -> Dict[str, Any]:
    return {
        "name": "mcp-task",
        "version": "0.1.0",
        "description": "Minimal MCP task orchestrator with SQLite persistence.",
        "endpoints": {"invoke": "/invoke", "sse": "/sse", "messages": "/messages"},
        "tools": _tool_list(),
    }


async def _invoke_remote(server: str, tool: str, args: Dict[str, Any]) -> Any:
    servers = _get_servers()

    requested = str(server or "").strip()
    base = servers.get(requested)
    if not base:
        # Compatibility: some UIs use their own labels for the target server.
        # Prefer mcp-devops as a sensible default if available.
        requested_l = requested.lower()
        if requested_l in ("openchat", "openchat-ui", "chat"):
            if "mcp-devops" in servers:
                requested = "mcp-devops"
                base = servers.get(requested)
            elif len(servers) == 1:
                requested = next(iter(servers.keys()))
                base = servers.get(requested)

    if not base:
        raise RuntimeError(f"Unknown server '{server}'. Known: {sorted(servers.keys())}")

    url = f"{base}/invoke"
    payload = {"tool": tool, "args": args}

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = None
            try:
                body = e.response.text
            except Exception:
                body = None
            detail = body.strip() if isinstance(body, str) else ""
            if len(detail) > 4000:
                detail = detail[:4000] + "..."
            msg = f"Remote invoke failed: {e.response.status_code} {e.response.reason_phrase} for {url}"
            if detail:
                msg = msg + f"; body={detail}"
            raise RuntimeError(msg) from e
        return r.json()


def _task_row(task_id: str) -> Optional[sqlite3.Row]:
    cur = _conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    return cur.fetchone()


def _latest_run_row(task_id: str) -> Optional[sqlite3.Row]:
    cur = _conn.execute(
        "SELECT * FROM runs WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    )
    return cur.fetchone()


def _runs_for_task(task_id: str, limit: int, offset: int) -> List[sqlite3.Row]:
    cur = _conn.execute(
        "SELECT * FROM runs WHERE task_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (task_id, limit, offset),
    )
    return list(cur.fetchall())


def _list_task_rows(status: Optional[str], limit: int, offset: int) -> List[sqlite3.Row]:
    if status:
        cur = _conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    else:
        cur = _conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    return list(cur.fetchall())


def _task_to_dict(row: sqlite3.Row, latest_run: Optional[sqlite3.Row]) -> Dict[str, Any]:
    out = dict(row)
    out["spec"] = json.loads(out.pop("spec_json"))
    if latest_run is not None:
        run = dict(latest_run)
        if run.get("report_json"):
            run["report"] = json.loads(run["report_json"])
        else:
            run["report"] = None
        run.pop("report_json", None)
        out["latest_run"] = run
    else:
        out["latest_run"] = None
    return out


async def _create_task(args: CreateTaskArgs) -> Dict[str, Any]:
    task_id = str(uuid.uuid4())
    spec = args.model_dump()
    now = _utc_ts()

    _conn.execute(
        """
        INSERT INTO tasks (task_id, title, status, created_at, spec_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (task_id, args.title, "pending", now, _json_dumps(spec)),
    )
    _conn.commit()

    row = _task_row(task_id)
    if row is None:
        raise RuntimeError("Failed to create task")

    return {"task": _task_to_dict(row, None)}


async def _update_task(args: UpdateTaskArgs) -> Dict[str, Any]:
    row = _task_row(args.task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")

    if row["status"] not in ("pending",):
        raise HTTPException(status_code=409, detail=f"task not pending (status={row['status']})")

    spec = json.loads(row["spec_json"]) if row["spec_json"] else {}

    if args.title is not None:
        spec["title"] = args.title

    if args.call is not None:
        call = spec.get("call") or {}
        if args.call.server is not None:
            call["server"] = args.call.server
        if args.call.tool is not None:
            call["tool"] = args.call.tool
        if args.call.args is not None:
            call["args"] = args.call.args
        spec["call"] = call

    title_to_store = str(args.title) if args.title is not None else str(row["title"])
    _conn.execute(
        "UPDATE tasks SET title=?, spec_json=? WHERE task_id=?",
        (title_to_store, _json_dumps(spec), args.task_id),
    )
    _conn.commit()

    updated = _task_row(args.task_id)
    if updated is None:
        raise RuntimeError("task disappeared")
    latest = _latest_run_row(args.task_id)
    return {"task": _task_to_dict(updated, latest)}


async def _approve_task(args: ApproveTaskArgs) -> Dict[str, Any]:
    row = _task_row(args.task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")

    if row["status"] not in ("pending",):
        raise HTTPException(status_code=409, detail=f"task not pending (status={row['status']})")

    now = _utc_ts()
    _conn.execute(
        "UPDATE tasks SET status=?, approved_at=?, approved_by=? WHERE task_id=?",
        ("approved", now, args.approved_by, args.task_id),
    )
    _conn.commit()

    run_id = str(uuid.uuid4())
    _conn.execute(
        "INSERT INTO runs (run_id, task_id, status, created_at) VALUES (?, ?, ?, ?)",
        (run_id, args.task_id, "running", now),
    )
    _conn.commit()

    spec = json.loads(row["spec_json"])
    call = spec.get("call") or {}

    try:
        result = await _invoke_remote(call.get("server", ""), call.get("tool", ""), call.get("args") or {})
        finished = _utc_ts()
        report = {"ok": True, "result": result}

        _conn.execute(
            "UPDATE runs SET status=?, finished_at=?, report_json=? WHERE run_id=?",
            ("succeeded", finished, _json_dumps(report), run_id),
        )
        _conn.execute(
            "UPDATE tasks SET status=?, last_error=NULL WHERE task_id=?",
            ("completed", args.task_id),
        )
        _conn.commit()
    except Exception as e:
        finished = _utc_ts()
        err = str(e)
        report = {"ok": False, "error": err}

        _conn.execute(
            "UPDATE runs SET status=?, finished_at=?, report_json=?, error=? WHERE run_id=?",
            ("failed", finished, _json_dumps(report), err, run_id),
        )
        _conn.execute(
            "UPDATE tasks SET status=?, last_error=? WHERE task_id=?",
            ("failed", err, args.task_id),
        )
        _conn.commit()

    task = _task_row(args.task_id)
    latest_run = _latest_run_row(args.task_id)
    if task is None:
        raise RuntimeError("task disappeared")

    return {"task": _task_to_dict(task, latest_run)}


async def _get_task(args: GetTaskArgs) -> Dict[str, Any]:
    row = _task_row(args.task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    latest = _latest_run_row(args.task_id)
    return {"task": _task_to_dict(row, latest)}


async def _get_task_report(args: GetTaskReportArgs) -> Dict[str, Any]:
    latest = _latest_run_row(args.task_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="no runs")
    report_json = latest["report_json"]
    report = json.loads(report_json) if report_json else None
    return {"task_id": args.task_id, "run_id": latest["run_id"], "report": report}


async def _list_tasks(args: ListTasksArgs) -> Dict[str, Any]:
    rows = _list_task_rows(args.status, args.limit, args.offset)
    tasks: List[Dict[str, Any]] = []
    for r in rows:
        latest = _latest_run_row(r["task_id"])
        tasks.append(_task_to_dict(r, latest))
    return {"tasks": tasks, "limit": args.limit, "offset": args.offset}


async def _list_runs(args: ListRunsArgs) -> Dict[str, Any]:
    task = _task_row(args.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    rows = _runs_for_task(args.task_id, args.limit, args.offset)
    runs: List[Dict[str, Any]] = []
    for r in rows:
        out = dict(r)
        if out.get("report_json"):
            out["report"] = json.loads(out["report_json"])
        else:
            out["report"] = None
        out.pop("report_json", None)
        runs.append(out)
    return {"task_id": args.task_id, "runs": runs, "limit": args.limit, "offset": args.offset}


async def _dispatch_tool(tool: str, args: Dict[str, Any]) -> Any:
    if tool == "create_task":
        model = CreateTaskArgs.model_validate(args)
        return await _create_task(model)
    if tool == "update_task":
        model = UpdateTaskArgs.model_validate(args)
        return await _update_task(model)
    if tool == "approve_task":
        model = ApproveTaskArgs.model_validate(args)
        return await _approve_task(model)
    if tool == "get_task":
        model = GetTaskArgs.model_validate(args)
        return await _get_task(model)
    if tool == "get_task_report":
        model = GetTaskReportArgs.model_validate(args)
        return await _get_task_report(model)
    if tool == "list_tasks":
        model = ListTasksArgs.model_validate(args)
        return await _list_tasks(model)
    if tool == "list_runs":
        model = ListRunsArgs.model_validate(args)
        return await _list_runs(model)
    if tool == "create_conversation":
        model = CreateConversationArgs.model_validate(args)
        now = _utc_ts()
        conversation_id = str(uuid.uuid4())
        title = (model.title or "").strip()
        title_to_store = title or f"Conversation {conversation_id[:8]}"
        meta_json = _json_dumps(model.meta) if isinstance(model.meta, dict) else None
        _conn.execute(
            "INSERT INTO conversations (conversation_id, title, source, created_at, updated_at, meta_json) VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, title_to_store, str(model.source or "chat"), now, now, meta_json),
        )
        _conn.commit()
        row = _conversation_row(conversation_id)
        if row is None:
            raise RuntimeError("Failed to create conversation")
        return {"conversation": _conversation_to_dict(row, [])}
    if tool == "append_conversation_message":
        model = AppendConversationMessageArgs.model_validate(args)
        conv = _conversation_row(model.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        now = _utc_ts()
        message_id = str(uuid.uuid4())
        meta_json = _json_dumps(model.meta) if isinstance(model.meta, dict) else None
        _conn.execute(
            "INSERT INTO conversation_messages (message_id, conversation_id, role, content, created_at, meta_json) VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, model.conversation_id, str(model.role), str(model.content), now, meta_json),
        )
        _conn.execute(
            "UPDATE conversations SET updated_at=? WHERE conversation_id=?",
            (now, model.conversation_id),
        )
        _conn.commit()
        return {"ok": True, "message_id": message_id, "conversation_id": model.conversation_id}
    if tool == "get_conversation":
        model = GetConversationArgs.model_validate(args)
        conv = _conversation_row(model.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        msgs = _conversation_message_rows(model.conversation_id, limit=500, offset=0)
        return {"conversation": _conversation_to_dict(conv, msgs)}
    if tool == "list_conversations":
        model = ListConversationsArgs.model_validate(args)
        rows = _list_conversation_rows(model.source, model.limit, model.offset)
        return {
            "conversations": [_conversation_to_dict(r) for r in rows],
            "limit": model.limit,
            "offset": model.offset,
        }
    raise HTTPException(status_code=404, detail=f"unknown tool: {tool}")


@app.post("/invoke")
async def invoke(req: Request) -> JSONResponse:
    body = await req.json()
    tool = body.get("tool")
    args = body.get("args") or {}
    if not tool:
        raise HTTPException(status_code=400, detail="missing tool")

    result = await _dispatch_tool(str(tool), dict(args))
    return JSONResponse(result)


@app.post("/mcp")
async def mcp_rpc(req: Request) -> JSONResponse:
    body = await req.json()
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        client_info = (params or {}).get("clientInfo") or {}
        _ = client_info
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": (params or {}).get("protocolVersion") or "2024-11-05",
                    "serverInfo": {"name": "mcp-task", "version": "0.1.0"},
                    "capabilities": {
                        "tools": {"listChanged": True},
                    },
                },
            },
            status_code=200,
        )

    if method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": None}, status_code=200)

    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}}, status_code=200)

    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_list()}})

    if method in ("tools/invoke", "tools/call"):
        tool = (params or {}).get("name")
        args = (params or {}).get("arguments") or {}
        try:
            res = await _dispatch_tool(tool, args)
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": res})
        except HTTPException as e:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": e.status_code, "message": str(e.detail)},
                },
                status_code=200,
            )

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": "method not found"},
        },
        status_code=200,
    )


@app.get("/sse")
async def sse(request: Request) -> StreamingResponse:
    session_id = str(uuid.uuid4())
    q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    _sessions[session_id] = SseSession(session_id=session_id, queue=q, created_at=_utc_ts())

    async def gen():
        endpoint = f"/messages?session_id={session_id}"
        yield f"event: endpoint\ndata: {endpoint}\n\n"
        yield f"event: ready\ndata: {session_id}\n\n"

        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                yield f"event: message\ndata: {_json_dumps(msg)}\n\n"
            except asyncio.TimeoutError:
                yield "event: ping\ndata: {}\n\n"

        _sessions.pop(session_id, None)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/messages")
async def sse_messages(session_id: str, req: Request) -> JSONResponse:
    sess = _sessions.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="unknown session")

    body = await req.json()
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    async def push(obj: Dict[str, Any]) -> None:
        await sess.queue.put(obj)

    if method == "tools/list":
        await push({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_list()}})
        return JSONResponse({"ok": True})

    if method in ("tools/invoke", "tools/call"):
        tool = (params or {}).get("name")
        args = (params or {}).get("arguments") or {}
        try:
            out = await _dispatch_tool(tool, args)
            await push({"jsonrpc": "2.0", "id": req_id, "result": out})
            return JSONResponse({"ok": True})
        except HTTPException as e:
            await push(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": e.status_code, "message": str(e.detail)},
                }
            )
        return JSONResponse({"ok": True})

    await push(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": "method not found"},
        }
    )
    return JSONResponse({"ok": True})
