import asyncio
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
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


def _db() -> sqlite3.Connection:
    db_path = _get_db_path()
    _ensure_dir_for_file(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
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
    conn.commit()


class ToolCall(BaseModel):
    server: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)


class CreateTaskArgs(BaseModel):
    title: str
    call: ToolCall


class ApproveTaskArgs(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))
    approved_by: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("approved_by", "approvedBy")
    )


class GetTaskArgs(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))


class GetTaskReportArgs(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))


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


def _tool_list() -> List[Dict[str, Any]]:
    return [
        {
            "name": "create_task",
            "description": "Create a task which, when approved, will invoke a tool on another MCP server.",
            "inputSchema": CreateTaskArgs.model_json_schema(),
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
    base = servers.get(server)
    if not base:
        raise RuntimeError(f"Unknown server '{server}'. Known: {sorted(servers.keys())}")

    url = f"{base}/invoke"
    payload = {"tool": tool, "args": args}

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
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


async def _dispatch_tool(tool: str, args: Dict[str, Any]) -> Any:
    if tool == "create_task":
        model = CreateTaskArgs.model_validate(args)
        return await _create_task(model)
    if tool == "approve_task":
        model = ApproveTaskArgs.model_validate(args)
        return await _approve_task(model)
    if tool == "get_task":
        model = GetTaskArgs.model_validate(args)
        return await _get_task(model)
    if tool == "get_task_report":
        model = GetTaskReportArgs.model_validate(args)
        return await _get_task_report(model)
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

    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_list()}})

    if method == "tools/invoke":
        tool = (params or {}).get("name")
        args = (params or {}).get("arguments") or {}
        try:
            res = await _dispatch_tool(str(tool), dict(args))
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

    if method == "tools/invoke":
        tool = (params or {}).get("name")
        args = (params or {}).get("arguments") or {}
        try:
            res = await _dispatch_tool(str(tool), dict(args))
            await push({"jsonrpc": "2.0", "id": req_id, "result": res})
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
