from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, Field

APP_NAME = "jarvis-backend"
APP_VERSION = "0.1.0"

logging.basicConfig(level=os.getenv("JARVIS_LOG_LEVEL", "INFO"))
logger = logging.getLogger(APP_NAME)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _get_port() -> int:
    return int(os.getenv("JARVIS_PORT", "18018"))


def _get_host() -> str:
    return str(os.getenv("JARVIS_HOST", "0.0.0.0"))


def _get_request_timeout() -> float:
    return float(os.getenv("JARVIS_REQUEST_TIMEOUT", "60"))


def _get_servers() -> Dict[str, str]:
    """Return a mapping of server-name -> base-url from env JARVIS_SERVERS (JSON array)."""
    raw = os.getenv("JARVIS_SERVERS", "[]")
    try:
        items = json.loads(raw)
        return {str(it["name"]).strip(): str(it["url"]).strip().rstrip("/") for it in items if it.get("name") and it.get("url")}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Macro registry
# ---------------------------------------------------------------------------

# A macro step is a dict with keys: server (str), tool (str), args (dict).
# The "server" value must match a key in the _get_servers() map at runtime,
# or be the special sentinel "__local__" for future local dispatch.
MacroStep = Dict[str, Any]
MacroDefinition = Dict[str, Any]  # {id, description, steps: List[MacroStep]}

_MACRO_REGISTRY: Dict[str, MacroDefinition] = {
    "health_check": {
        "id": "health_check",
        "description": "Ping the jarvis-backend /health endpoint to confirm the service is alive.",
        "steps": [
            {"server": "__self__", "tool": "self_health", "args": {}},
        ],
    },
    "devops_telemetry": {
        "id": "devops_telemetry",
        "description": "Collect system telemetry from mcp-devops.",
        "steps": [
            {"server": "mcp-devops", "tool": "system_telemetry", "args": {"question": "system overview"}},
        ],
    },
    "devops_list_workflows": {
        "id": "devops_list_workflows",
        "description": "List all available DevOps workflows from mcp-devops.",
        "steps": [
            {"server": "mcp-devops", "tool": "list_workflows", "args": {}},
        ],
    },
}

# Sensitive argument key patterns – values are redacted from step summaries.
_SECRET_KEY_RE = re.compile(r"(token|secret|password|key|auth|credential)", re.IGNORECASE)


def _redact_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of args with secret-looking values replaced with '***'."""
    out: Dict[str, Any] = {}
    for k, v in args.items():
        if _SECRET_KEY_RE.search(str(k)):
            out[k] = "***"
        else:
            out[k] = v
    return out


def list_macros() -> List[Dict[str, Any]]:
    return [
        {"id": m["id"], "description": m["description"]}
        for m in _MACRO_REGISTRY.values()
    ]


def get_macro(macro_id: str) -> Optional[MacroDefinition]:
    return _MACRO_REGISTRY.get(macro_id)


# ---------------------------------------------------------------------------
# Remote tool invocation
# ---------------------------------------------------------------------------

async def _invoke_remote(server: str, tool: str, args: Dict[str, Any], timeout: float) -> Any:
    servers = _get_servers()
    base = servers.get(server)
    if not base:
        raise ValueError(f"Unknown server '{server}'. Configure it via JARVIS_SERVERS.")

    url = f"{base}/invoke"
    payload = {"tool": tool, "args": args}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# system_run_macro implementation
# ---------------------------------------------------------------------------

class RunMacroArgs(BaseModel):
    macro: str = Field(description="Macro name / id to run.")
    args: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("args", "arguments"),
        description="Optional top-level args merged into each step's args.",
    )


async def _run_macro(macro_id: str, extra_args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a named macro and return a structured result.

    Return shape:
    {
        "ok": bool,
        "macro": str,
        "steps": [{"tool": str, "ok": bool, "error": str|null}],
        "result": <last step output when ok>,
        "error": <string or object when not ok>
    }
    """
    macro = get_macro(macro_id)
    if macro is None:
        return {
            "ok": False,
            "macro": macro_id,
            "steps": [],
            "error": f"Macro '{macro_id}' not found. Available: {list(_MACRO_REGISTRY.keys())}",
        }

    steps_summary: List[Dict[str, Any]] = []
    last_result: Any = None
    timeout = _get_request_timeout()

    for step in macro.get("steps", []):
        server = str(step.get("server", ""))
        tool = str(step.get("tool", ""))
        step_args: Dict[str, Any] = {**(step.get("args") or {}), **extra_args}

        step_summary: Dict[str, Any] = {
            "tool": tool,
            "ok": False,
            "error": None,
        }

        try:
            if server == "__self__":
                # Internal self-check step
                last_result = {"ok": True, "service": APP_NAME, "version": APP_VERSION}
            else:
                last_result = await _invoke_remote(server, tool, step_args, timeout)

            step_summary["ok"] = True
        except Exception as exc:
            err_str = str(exc)
            step_summary["error"] = err_str
            steps_summary.append(step_summary)
            return {
                "ok": False,
                "macro": macro_id,
                "steps": steps_summary,
                "error": f"Step '{tool}' on '{server}' failed: {err_str}",
            }

        steps_summary.append(step_summary)

    return {
        "ok": True,
        "macro": macro_id,
        "steps": steps_summary,
        "result": last_result,
    }


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

class ListMacrosArgs(BaseModel):
    pass


TOOLS = {
    "system_run_macro": {
        "name": "system_run_macro",
        "description": (
            "Run a named macro server-side. "
            "Returns structured output: ok, macro, steps (tool + ok/error per step), "
            "and result or error."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["macro"],
            "properties": {
                "macro": {"type": "string", "description": "Macro name / id to run."},
                "args": {
                    "type": "object",
                    "description": "Optional extra args merged into each macro step.",
                },
            },
        },
    },
    "list_macros": {
        "name": "list_macros",
        "description": "List all available macros with their ids and descriptions.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
}


async def _dispatch_tool(tool: str, args: Dict[str, Any]) -> Any:
    if tool == "system_run_macro":
        model = RunMacroArgs.model_validate(args)
        return await _run_macro(model.macro, dict(model.args))
    if tool == "list_macros":
        return {"macros": list_macros()}
    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool}")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": APP_NAME, "version": APP_VERSION}


@app.get("/jarvis/api/debug/status")
def debug_status() -> Dict[str, Any]:
    servers = _get_servers()
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "macros_count": len(_MACRO_REGISTRY),
        "dependencies": {
            name: {"configured": True, "url": url}
            for name, url in servers.items()
        },
    }


@app.get("/jarvis/api/macros")
def api_list_macros() -> Dict[str, Any]:
    return {"macros": list_macros()}


@app.post("/invoke")
async def invoke(req: Request) -> JSONResponse:
    body = await req.json()
    tool = body.get("tool")
    args: Dict[str, Any] = body.get("args") or {}
    if not tool:
        raise HTTPException(status_code=400, detail="Missing 'tool' in request body.")
    result = await _dispatch_tool(str(tool), dict(args))
    return JSONResponse(result)


@app.post("/mcp")
async def mcp_rpc(req: Request) -> JSONResponse:
    body = await req.json()
    req_id = body.get("id")
    method = str(body.get("method") or "")
    params = body.get("params") or {}

    def _ok(result: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _err(code: int, message: str) -> JSONResponse:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}},
            status_code=400,
        )

    if method == "initialize":
        return JSONResponse(
            _ok({
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "capabilities": {"tools": {}},
            })
        )

    if method == "notifications/initialized":
        return JSONResponse({}, status_code=204)

    if method == "tools/list":
        return JSONResponse(_ok({"tools": list(TOOLS.values())}))

    if method in ("tools/call", "tools/invoke"):
        tool_name = params.get("name") or params.get("tool")
        raw_args = params.get("arguments") or params.get("args") or {}
        if isinstance(raw_args, str):
            try:
                raw_args = json.loads(raw_args)
            except Exception:
                raw_args = {}
        if not tool_name:
            return _err(-32602, "params.name is required")
        if tool_name not in TOOLS:
            return _err(-32601, f"Unknown tool '{tool_name}'")
        try:
            result = await _dispatch_tool(str(tool_name), dict(raw_args))
            return JSONResponse(
                _ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
            )
        except HTTPException as exc:
            return _err(-32601, exc.detail)
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return _err(-32000, str(exc))

    return _err(-32601, f"Method '{method}' not found")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=_get_host(),
        port=_get_port(),
        reload=False,
    )
