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


class ListRunsArgs(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class RunPc1TestsArgs(BaseModel):
    prefix: str = Field(default="test-pc1-", description="Only run tests whose name starts with this prefix")
    server: str = Field(default="mcp-tester", description="Remote tester server name as configured in MCP_TASK_SERVERS")
    tests: Optional[List[str]] = Field(default=None, description="Optional explicit test names override")
    fail_fast: bool = Field(default=True)
    concurrency: int = Field(default=1, ge=1, le=16, description="Number of concurrent chunks to run")
    chunk_size: Optional[int] = Field(
        default=None, ge=1, description="Optional explicit chunk size (overrides concurrency-based chunking)"
    )
    timeout_ms: Optional[int] = Field(default=None)
    retries: Optional[int] = Field(default=None)
    retry_delay_ms: Optional[int] = Field(default=None)
    title: Optional[str] = Field(default=None, description="Optional title to store in mcp-task history")
    include_raw: bool = Field(default=False, description="Include the raw mcp-tester response in the report")


class RunTestPc1McpRagcudaArgs(BaseModel):
    fail_fast: bool = Field(default=False)
    concurrency: int = Field(default=8, ge=1, le=16)
    chunk_size: int = Field(default=1, ge=1)
    timeout_ms: Optional[int] = Field(default=None)
    retries: Optional[int] = Field(default=None)
    retry_delay_ms: Optional[int] = Field(default=None)
    title: Optional[str] = Field(default=None)
    include_raw: bool = Field(default=False)


class DeployPc1StackArgs(BaseModel):
    workflow_id: str = Field(default="deploy-pc1-stack")
    dry_run: bool = Field(default=True)
    run_tests: bool = Field(default=True)
    test_concurrency: int = Field(default=8, ge=1, le=16)
    test_chunk_size: int = Field(default=1, ge=1)
    test_fail_fast: bool = Field(default=False)
    title: Optional[str] = Field(default=None)
    include_raw: bool = Field(default=False)


class PrepareDeployPc1StackArgs(BaseModel):
    workflow_id: str = Field(default="deploy-pc1-stack")
    run_tests: bool = Field(default=True)
    test_concurrency: int = Field(default=8, ge=1, le=16)
    test_chunk_size: int = Field(default=1, ge=1)
    test_fail_fast: bool = Field(default=False)
    title: Optional[str] = Field(default=None)
    include_raw: bool = Field(default=False)


class PublishPc1StackArgs(BaseModel):
    workflow_id: str = Field(default="deploy-pc1-stack")
    dry_run: bool = Field(default=True)
    run_tests: bool = Field(default=True)
    run_verify: bool = Field(default=True)
    test_concurrency: int = Field(default=8, ge=1, le=16)
    test_chunk_size: int = Field(default=1, ge=1)
    test_fail_fast: bool = Field(default=False)
    title: Optional[str] = Field(default=None)
    include_raw: bool = Field(default=False)


class PreparePublishPc1StackArgs(BaseModel):
    workflow_id: str = Field(default="deploy-pc1-stack")
    run_tests: bool = Field(default=True)
    run_verify: bool = Field(default=True)
    test_concurrency: int = Field(default=8, ge=1, le=16)
    test_chunk_size: int = Field(default=1, ge=1)
    test_fail_fast: bool = Field(default=False)
    title: Optional[str] = Field(default=None)
    include_raw: bool = Field(default=False)


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
        f"<div class='row'><a href='/control'>Control</a><span class='muted'>/</span><span class='muted'>{escape(title)}</span></div>"
        f"<h1>{escape(title)}</h1>"
        f"{body}"
        "</body></html>"
    )
    return HTMLResponse(html)


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
            "name": "run_pc1_tests",
            "description": "Run mcp-tester tests by prefix (e.g. pc1- or test-pc1-) and store a summarized report.",
            "inputSchema": RunPc1TestsArgs.model_json_schema(),
        },
        {
            "name": "run_test_pc1_mcp_ragcuda",
            "description": "Run the test-pc1-mcp-ragcuda- suite with concurrent execution and store a summarized report.",
            "inputSchema": RunTestPc1McpRagcudaArgs.model_json_schema(),
        },
        {
            "name": "deploy_pc1_stack",
            "description": "Deploy pc1-stack via mcp-devops workflow (dry-run by default) then run test-pc1-mcp-ragcuda smoke suite and store a combined report.",
            "inputSchema": DeployPc1StackArgs.model_json_schema(),
        },
        {
            "name": "prepare_deploy_pc1_stack",
            "description": "Create an approval-gated deploy task for pc1-stack. Use approve_task to execute.",
            "inputSchema": PrepareDeployPc1StackArgs.model_json_schema(),
        },
        {
            "name": "publish_pc1_stack",
            "description": "Publish pc1-stack: deploy via mcp-devops, run ragcuda smoke tests, then verify key health endpoints; store a single combined report.",
            "inputSchema": PublishPc1StackArgs.model_json_schema(),
        },
        {
            "name": "prepare_publish_pc1_stack",
            "description": "Create an approval-gated publish task for pc1-stack. Use approve_task to execute.",
            "inputSchema": PreparePublishPc1StackArgs.model_json_schema(),
        },
    ]


def _is_local_server_name(name: str) -> bool:
    n = (name or "").strip().lower()
    return n in ("local", "self", "mcp-task", "mcp_task")


async def _invoke_local(tool: str, args: Dict[str, Any]) -> Any:
    # Keep this allowlist tight to avoid turning mcp-task into an arbitrary executor.
    allowed = {
        "deploy_pc1_stack",
        "publish_pc1_stack",
        "run_pc1_tests",
        "run_test_pc1_mcp_ragcuda",
    }
    if tool not in allowed:
        raise RuntimeError(f"Local tool '{tool}' is not allowed")
    return await _dispatch_tool(tool, args)


async def _run_test_pc1_mcp_ragcuda(args: RunTestPc1McpRagcudaArgs) -> Dict[str, Any]:
    inner = RunPc1TestsArgs(
        prefix="test-pc1-mcp-ragcuda-",
        server="mcp-tester",
        fail_fast=bool(args.fail_fast),
        concurrency=int(args.concurrency),
        chunk_size=int(args.chunk_size),
        timeout_ms=args.timeout_ms,
        retries=args.retries,
        retry_delay_ms=args.retry_delay_ms,
        title=args.title,
        include_raw=bool(args.include_raw),
    )
    return await _run_pc1_tests(inner)


async def _deploy_pc1_stack(args: DeployPc1StackArgs) -> Dict[str, Any]:
    workflow_id = (args.workflow_id or "").strip() or "deploy-pc1-stack"
    title = (args.title or f"Deploy pc1-stack ({'dry-run' if args.dry_run else 'apply'})").strip()
    if not title:
        title = f"Deploy pc1-stack ({'dry-run' if args.dry_run else 'apply'})"

    # Run deploy workflow via mcp-devops.
    deploy_out = await _invoke_remote(
        "mcp-devops",
        "run_workflow",
        {"workflow_id": workflow_id, "dry_run": bool(args.dry_run)},
    )

    tests_out: Optional[Dict[str, Any]] = None
    if not bool(args.dry_run) and bool(args.run_tests):
        tests_out = await _run_test_pc1_mcp_ragcuda(
            RunTestPc1McpRagcudaArgs(
                fail_fast=bool(args.test_fail_fast),
                concurrency=int(args.test_concurrency),
                chunk_size=int(args.test_chunk_size),
                title=f"Post-deploy smoke: {workflow_id}",
                include_raw=bool(args.include_raw),
            )
        )

    report: Dict[str, Any] = {
        "ok": True,
        "workflow": {"workflow_id": workflow_id, "dry_run": bool(args.dry_run)},
        "deploy": deploy_out,
        "tests": tests_out,
    }

    # Determine ok status.
    # mcp-devops /invoke run_workflow returns {exit_code:..., error_code:..., dry_run:...}
    if isinstance(deploy_out, dict):
        exit_code = deploy_out.get("exit_code")
        error_code = deploy_out.get("error_code")
        dry_run_flag = bool(deploy_out.get("dry_run"))
        if not dry_run_flag:
            if exit_code not in (0, None):
                report["ok"] = False
            if error_code:
                report["ok"] = False

    if tests_out and isinstance(tests_out, dict):
        inner_report = tests_out.get("report") if isinstance(tests_out.get("report"), dict) else None
        if isinstance(inner_report, dict) and inner_report.get("ok") is False:
            report["ok"] = False

    # Persist combined report as a completed task.
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    now = _utc_ts()
    spec = {
        "title": title,
        "call": {"server": "mcp-devops", "tool": "run_workflow", "args": {"workflow_id": workflow_id}},
        "meta": {"kind": "deploy_pc1_stack", "dry_run": bool(args.dry_run)},
    }

    _conn.execute(
        "INSERT INTO tasks (task_id, title, status, created_at, approved_at, approved_by, spec_json, last_error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id,
            title,
            "completed" if report["ok"] else "failed",
            now,
            now,
            "mcp-task",
            _json_dumps(spec),
            None,
        ),
    )
    _conn.execute(
        "INSERT INTO runs (run_id, task_id, status, created_at, finished_at, report_json, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            task_id,
            "succeeded" if report["ok"] else "failed",
            now,
            now,
            _json_dumps(report),
            None if report["ok"] else "deploy_or_tests_failed",
        ),
    )
    _conn.commit()

    return {"task_id": task_id, "run_id": run_id, "report": report}


async def _prepare_deploy_pc1_stack(args: PrepareDeployPc1StackArgs) -> Dict[str, Any]:
    title = (args.title or f"Deploy pc1-stack (approval required)").strip() or "Deploy pc1-stack (approval required)"
    call = ToolCall(
        server="local",
        tool="deploy_pc1_stack",
        args={
            "workflow_id": (args.workflow_id or "deploy-pc1-stack").strip() or "deploy-pc1-stack",
            "dry_run": False,
            "run_tests": bool(args.run_tests),
            "test_concurrency": int(args.test_concurrency),
            "test_chunk_size": int(args.test_chunk_size),
            "test_fail_fast": bool(args.test_fail_fast),
            "title": title,
            "include_raw": bool(args.include_raw),
        },
    )
    created = await _create_task(CreateTaskArgs(title=title, call=call))
    return created


async def _verify_pc1_stack_health() -> Dict[str, Any]:
    checks = [
        {"name": "1mcp-agent", "url": "http://1mcp-agent:3051/health"},
        {"name": "mcp-rag", "url": "http://mcp-rag:8055/health"},
        {"name": "mcp-cuda", "url": "http://mcp-cuda:8057/health"},
        {"name": "mcp-tester", "url": "http://mcp-tester:8335/health"},
        {"name": "mcp-devops", "url": "http://mcp-devops:8325/health"},
    ]

    out: List[Dict[str, Any]] = []
    ok = True
    async with httpx.AsyncClient(timeout=10.0) as client:
        for chk in checks:
            name = str(chk["name"])
            url = str(chk["url"])
            try:
                resp = await client.get(url)
                entry = {
                    "name": name,
                    "url": url,
                    "status_code": int(resp.status_code),
                    "ok": bool(200 <= resp.status_code < 300),
                }
            except Exception as e:
                entry = {"name": name, "url": url, "status_code": None, "ok": False, "error": str(e)}
            if not entry.get("ok"):
                ok = False
            out.append(entry)
    return {"ok": ok, "checks": out}


async def _publish_pc1_stack(args: PublishPc1StackArgs) -> Dict[str, Any]:
    workflow_id = (args.workflow_id or "").strip() or "deploy-pc1-stack"
    title = (args.title or f"Publish pc1-stack ({'dry-run' if args.dry_run else 'apply'})").strip()
    if not title:
        title = f"Publish pc1-stack ({'dry-run' if args.dry_run else 'apply'})"

    deploy_out = await _invoke_remote(
        "mcp-devops",
        "run_workflow",
        {"workflow_id": workflow_id, "dry_run": bool(args.dry_run)},
    )

    tests_out: Optional[Dict[str, Any]] = None
    if not bool(args.dry_run) and bool(args.run_tests):
        tests_out = await _run_test_pc1_mcp_ragcuda(
            RunTestPc1McpRagcudaArgs(
                fail_fast=bool(args.test_fail_fast),
                concurrency=int(args.test_concurrency),
                chunk_size=int(args.test_chunk_size),
                title=f"Post-publish smoke: {workflow_id}",
                include_raw=bool(args.include_raw),
            )
        )

    verify_out: Optional[Dict[str, Any]] = None
    if not bool(args.dry_run) and bool(args.run_verify):
        verify_out = await _verify_pc1_stack_health()

    report: Dict[str, Any] = {
        "ok": True,
        "workflow": {"workflow_id": workflow_id, "dry_run": bool(args.dry_run)},
        "deploy": deploy_out,
        "tests": tests_out,
        "verify": verify_out,
    }

    if isinstance(deploy_out, dict):
        exit_code = deploy_out.get("exit_code")
        error_code = deploy_out.get("error_code")
        dry_run_flag = bool(deploy_out.get("dry_run"))
        if not dry_run_flag:
            if exit_code not in (0, None):
                report["ok"] = False
            if error_code:
                report["ok"] = False

    if tests_out and isinstance(tests_out, dict):
        inner_report = tests_out.get("report") if isinstance(tests_out.get("report"), dict) else None
        if isinstance(inner_report, dict) and inner_report.get("ok") is False:
            report["ok"] = False

    if verify_out and isinstance(verify_out, dict) and verify_out.get("ok") is False:
        report["ok"] = False

    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    now = _utc_ts()
    spec = {
        "title": title,
        "call": {"server": "mcp-devops", "tool": "run_workflow", "args": {"workflow_id": workflow_id}},
        "meta": {"kind": "publish_pc1_stack", "dry_run": bool(args.dry_run)},
    }

    _conn.execute(
        "INSERT INTO tasks (task_id, title, status, created_at, approved_at, approved_by, spec_json, last_error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id,
            title,
            "completed" if report["ok"] else "failed",
            now,
            now,
            "mcp-task",
            _json_dumps(spec),
            None,
        ),
    )
    _conn.execute(
        "INSERT INTO runs (run_id, task_id, status, created_at, finished_at, report_json, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            task_id,
            "succeeded" if report["ok"] else "failed",
            now,
            now,
            _json_dumps(report),
            None if report["ok"] else "publish_failed",
        ),
    )
    _conn.commit()

    return {"task_id": task_id, "run_id": run_id, "report": report}


async def _prepare_publish_pc1_stack(args: PreparePublishPc1StackArgs) -> Dict[str, Any]:
    title = (args.title or f"Publish pc1-stack (approval required)").strip() or "Publish pc1-stack (approval required)"
    call = ToolCall(
        server="local",
        tool="publish_pc1_stack",
        args={
            "workflow_id": (args.workflow_id or "deploy-pc1-stack").strip() or "deploy-pc1-stack",
            "dry_run": False,
            "run_tests": bool(args.run_tests),
            "run_verify": bool(args.run_verify),
            "test_concurrency": int(args.test_concurrency),
            "test_chunk_size": int(args.test_chunk_size),
            "test_fail_fast": bool(args.test_fail_fast),
            "title": title,
            "include_raw": bool(args.include_raw),
        },
    )
    created = await _create_task(CreateTaskArgs(title=title, call=call))
    return created


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
    # Compatibility: different MCP servers expect either 'args' or 'arguments'.
    payload = {"tool": tool, "args": args, "arguments": args}

    last_exc: Optional[BaseException] = None
    # Retries are important during deploy: docker compose up may briefly restart services.
    for attempt in range(1, 6):
        try:
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
        except (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpx.TimeoutException,
        ) as e:
            last_exc = e
            if attempt >= 5:
                break
            # Linear backoff: 1s, 2s, 3s, 4s
            await asyncio.sleep(float(attempt))
        except Exception as e:  # noqa: BLE001
            # Non-transient (or unknown): do not hide it behind retries.
            raise

    raise RuntimeError(f"All connection attempts failed for {url}") from last_exc


def _summarize_mcp_tester_run(summary: Dict[str, Any]) -> Dict[str, Any]:
    results = summary.get("results") if isinstance(summary, dict) else None
    if not isinstance(results, list):
        results = []

    failures: List[Dict[str, Any]] = []
    skipped = 0
    for r in results:
        if not isinstance(r, dict):
            continue
        status = r.get("status")
        if status == "skipped":
            skipped += 1
        if status != "passed":
            failures.append(
                {
                    "name": r.get("name"),
                    "status": status,
                    "target_url": r.get("target_url"),
                    "method": r.get("method"),
                    "expect_status": r.get("expect_status"),
                    "actual_status": r.get("actual_status"),
                    "latency_ms": r.get("latency_ms"),
                    "attempts": r.get("attempts"),
                    "error": r.get("error"),
                    "body_excerpt": r.get("body_excerpt"),
                }
            )

    return {
        "run_id": summary.get("run_id"),
        "started_at": summary.get("started_at"),
        "completed_at": summary.get("completed_at"),
        "duration_ms": summary.get("duration_ms"),
        "total": summary.get("total"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "skipped": skipped,
        "failures": failures,
    }


def _chunk_list(items: List[str], size: int) -> List[List[str]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _aggregate_chunk_summaries(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = 0
    passed = 0
    failed = 0
    skipped = 0
    failures: List[Dict[str, Any]] = []
    started_at = None
    completed_at = None
    duration_ms = 0

    for ch in chunks:
        summary = ch.get("summary") if isinstance(ch, dict) else None
        if not isinstance(summary, dict):
            continue
        total += int(summary.get("total") or 0)
        passed += int(summary.get("passed") or 0)
        failed += int(summary.get("failed") or 0)
        skipped += int(summary.get("skipped") or 0)
        duration_ms += int(summary.get("duration_ms") or 0)
        if isinstance(summary.get("failures"), list):
            failures.extend(summary.get("failures"))

        # Preserve first seen timestamps (strings) for convenience.
        if started_at is None and summary.get("started_at"):
            started_at = summary.get("started_at")
        if summary.get("completed_at"):
            completed_at = summary.get("completed_at")

    return {
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "failures": failures,
    }


async def _run_pc1_tests(args: RunPc1TestsArgs) -> Dict[str, Any]:
    prefix = (args.prefix or "").strip()
    if not prefix:
        raise HTTPException(status_code=400, detail="prefix is required")

    # Discover tests
    if args.tests:
        selected = [str(x).strip() for x in (args.tests or []) if str(x).strip()]
    else:
        listed = await _invoke_remote(args.server, "list_tests", {})
        result = listed.get("result") if isinstance(listed, dict) else None
        tests = result.get("tests") if isinstance(result, dict) else None
        if not isinstance(tests, list):
            raise RuntimeError("mcp-tester list_tests returned invalid payload")
        selected = [str(t.get("name") or "").strip() for t in tests if isinstance(t, dict)]
        selected = [n for n in selected if n.startswith(prefix)]

    if not selected:
        raise HTTPException(status_code=404, detail=f"No tests matched prefix '{prefix}'")

    # Concurrency strategy: split selected tests into chunks and run them in parallel.
    desired_conc = max(1, min(int(args.concurrency or 1), 16))
    if args.chunk_size is not None:
        chunk_size = int(args.chunk_size)
    else:
        chunk_size = max(1, (len(selected) + desired_conc - 1) // desired_conc)

    test_chunks = _chunk_list(selected, chunk_size)

    base_run_args: Dict[str, Any] = {"fail_fast": bool(args.fail_fast)}
    if args.timeout_ms is not None:
        base_run_args["timeout_ms"] = int(args.timeout_ms)
    if args.retries is not None:
        base_run_args["retries"] = int(args.retries)
    if args.retry_delay_ms is not None:
        base_run_args["retry_delay_ms"] = int(args.retry_delay_ms)

    async def run_one(index: int, tests_subset: List[str]) -> Dict[str, Any]:
        run_args = dict(base_run_args)
        run_args["tests"] = tests_subset
        try:
            remote = await _invoke_remote(args.server, "run_tests", run_args)
            remote_result = remote.get("result") if isinstance(remote, dict) else None
            if not isinstance(remote_result, dict):
                raise RuntimeError("mcp-tester run_tests returned invalid payload")
            return {
                "chunk": index,
                "tests": tests_subset,
                "ok": bool((remote_result.get("failed") or 0) == 0),
                "summary": _summarize_mcp_tester_run(remote_result),
                "raw": remote_result,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "chunk": index,
                "tests": tests_subset,
                "ok": False,
                "error": str(exc),
            }

    # Run chunks concurrently (bounded by args.concurrency)
    semaphore = asyncio.Semaphore(desired_conc)

    async def guarded(index: int, tests_subset: List[str]) -> Dict[str, Any]:
        async with semaphore:
            return await run_one(index, tests_subset)

    chunk_results = await asyncio.gather(
        *(guarded(i, ch) for i, ch in enumerate(test_chunks)),
        return_exceptions=False,
    )

    chunk_summaries: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for cr in chunk_results:
        if not isinstance(cr, dict):
            continue
        if cr.get("summary"):
            chunk_summaries.append({"summary": cr.get("summary")})
        if cr.get("error"):
            errors.append({"chunk": cr.get("chunk"), "error": cr.get("error"), "tests": cr.get("tests")})

    report_summary = _aggregate_chunk_summaries(chunk_summaries)

    title = (args.title or f"Run tests prefix={prefix}").strip() or f"Run tests prefix={prefix}"
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    now = _utc_ts()

    spec = {
        "title": title,
        "call": {"server": args.server, "tool": "run_tests", "args": {"prefix": prefix}},
        "meta": {
            "kind": "pc1_tests",
            "prefix": prefix,
            "concurrency": desired_conc,
            "chunk_size": chunk_size,
        },
    }

    report: Dict[str, Any] = {
        "ok": bool((report_summary.get("failed") or 0) == 0) and not errors,
        "server": args.server,
        "prefix": prefix,
        "tests": selected,
        "summary": report_summary,
        "chunks": [
            {
                "chunk": cr.get("chunk"),
                "ok": bool(cr.get("ok")),
                "tests": cr.get("tests"),
                "summary": cr.get("summary"),
                "error": cr.get("error"),
            }
            for cr in chunk_results
            if isinstance(cr, dict)
        ],
        "errors": errors,
    }
    if args.include_raw:
        report["raw"] = [cr.get("raw") for cr in chunk_results if isinstance(cr, dict) and cr.get("raw")]

    _conn.execute(
        "INSERT INTO tasks (task_id, title, status, created_at, approved_at, approved_by, spec_json, last_error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, title, "completed" if report["ok"] else "failed", now, now, "mcp-task", _json_dumps(spec), None),
    )
    _conn.execute(
        "INSERT INTO runs (run_id, task_id, status, created_at, finished_at, report_json, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            task_id,
            "succeeded" if report["ok"] else "failed",
            now,
            now,
            _json_dumps(report),
            None if report["ok"] else "test_failures",
        ),
    )
    _conn.commit()

    return {"task_id": task_id, "run_id": run_id, "report": report}


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
        call_server = call.get("server", "")
        call_tool = call.get("tool", "")
        call_args = call.get("args") or {}
        if _is_local_server_name(str(call_server)):
            result = await _invoke_local(str(call_tool), dict(call_args))
        else:
            result = await _invoke_remote(str(call_server), str(call_tool), dict(call_args))
        finished = _utc_ts()

        ok = True
        # If the tool returns a nested report (common for local orchestration tools), propagate it.
        if isinstance(result, dict):
            nested = result.get("report")
            if isinstance(nested, dict) and nested.get("ok") is False:
                ok = False
        report = {"ok": ok, "result": result}

        _conn.execute(
            "UPDATE runs SET status=?, finished_at=?, report_json=?, error=? WHERE run_id=?",
            (
                "succeeded" if ok else "failed",
                finished,
                _json_dumps(report),
                None if ok else "nested_tool_failed",
                run_id,
            ),
        )
        _conn.execute(
            "UPDATE tasks SET status=?, last_error=? WHERE task_id=?",
            (
                "completed" if ok else "failed",
                None if ok else "nested_tool_failed",
                args.task_id,
            ),
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
    if tool == "run_pc1_tests":
        model = RunPc1TestsArgs.model_validate(args)
        return await _run_pc1_tests(model)
    if tool == "run_test_pc1_mcp_ragcuda":
        model = RunTestPc1McpRagcudaArgs.model_validate(args)
        return await _run_test_pc1_mcp_ragcuda(model)
    if tool == "deploy_pc1_stack":
        model = DeployPc1StackArgs.model_validate(args)
        return await _deploy_pc1_stack(model)
    if tool == "prepare_deploy_pc1_stack":
        model = PrepareDeployPc1StackArgs.model_validate(args)
        return await _prepare_deploy_pc1_stack(model)
    if tool == "publish_pc1_stack":
        model = PublishPc1StackArgs.model_validate(args)
        return await _publish_pc1_stack(model)
    if tool == "prepare_publish_pc1_stack":
        model = PreparePublishPc1StackArgs.model_validate(args)
        return await _prepare_publish_pc1_stack(model)
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
