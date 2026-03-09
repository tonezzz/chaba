import asyncio
import base64
import os
import logging
import json
import sqlite3
import time
import uuid
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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


SESSION_DB_PATH = os.getenv("JARVIS_SESSION_DB", "/app/jarvis_sessions.sqlite")


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
        conn.commit()


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
    observations = args.get("observations")
    if not isinstance(observations, list):
        observations = [description]
    else:
        # Normalize observations to strings
        observations = [str(o) for o in observations if str(o).strip()]
        if not observations:
            observations = [description]

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
        return await _aim_mcp_tools_call(mcp_name, adapted)
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
