#!/usr/bin/env python3
"""Minimal MCP server for focus operations."""
import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from mcp_debug.focus import mcp_focus


def _send(message):
    print(json.dumps(message), flush=True)


def handle_initialize(id_):
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mcp-focus", "version": "1"},
        },
    }


def handle_tools_list(id_):
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {
            "tools": [
                {
                    "name": "mcp_focus",
                    "description": "Focus intake and status: classify a request, get active foci, or run pre_action summary. Modes: recommend (default), status, pre_action, safe_next, ready_queue, defer, resume, sweep.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "request": {"type": "string", "description": "User request or defer reason"},
                            "mode": {"type": "string", "enum": ["recommend", "status", "reload", "pre_action", "safe_next", "ready_queue", "defer", "resume", "sweep", "next"], "default": "recommend", "description": "recommend returns the next focus recommendation; status returns current foci; reload explicitly re-reads files and returns current foci; safe_next returns the highest safe-to-parallel focus; defer parks the active focus and marks a resume note; resume suggests a focus to reactivate; sweep returns all parked/backlog/inbox candidates and optionally bulk-defers them to a named session; next activates the highest-priority parked/deferred focus"},
                            "resume_session": {"type": "string", "description": "Target session identifier for defer, or filter for resume"},
                            "reason": {"type": "string", "description": "Reason for deferring"},
                            "hold": {"type": "string", "description": "Label of the focus to hold while sweeping the rest"},
                            "bulk_session": {"type": "string", "description": "If provided in sweep mode, non-hold candidates without a session_map match are bulk-deferred to this session"},
                            "session_map": {"type": "object", "description": "Optional mapping of label/branch/default to session for sweep bulk-defer"},
                        },
                        "required": [],
                    },
                },
                {
                    "name": "mcp_focus_status",
                    "description": "Return the current active foci, quick wins, and hand-off queue.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ]
        },
    }


def handle_tools_call(id_, params):
    name = params.get("name")
    arguments = params.get("arguments", {})
    if name == "mcp_focus":
        request = arguments.get("request", "")
        mode = arguments.get("mode", "")
        result = mcp_focus(
            request,
            mode,
            resume_session=arguments.get("resume_session"),
            reason=arguments.get("reason"),
            hold=arguments.get("hold"),
            bulk_session=arguments.get("bulk_session"),
            session_map=arguments.get("session_map"),
        )
        _send({"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}})
        return
    if name == "mcp_focus_status":
        result = mcp_focus("", "status")
        _send({"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}})
        return
    _send({"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": f"unknown tool: {name}"}})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        id_ = msg.get("id")
        if method == "initialize":
            _send(handle_initialize(id_))
        elif method == "tools/list":
            _send(handle_tools_list(id_))
        elif method == "tools/call":
            handle_tools_call(id_, msg.get("params", {}))


if __name__ == "__main__":
    main()
