"""MCP Debug server wiring."""
import json
import logging
import sys
from .config import HOSTS, DEBUG_COMMANDS, PRESETS, PRESET_DESCRIPTIONS
from .hosts import run_on_host
from .tools import (
    mcp_debug,
    mcp_raw,
    mcp_stats,
    mcp_vet,
    mcp_savings,
    mcp_diff,
    mcp_logs,
    mcp_net,
    mcp_env,
    mcp_gpu,
    mcp_health,
    mcp_adaptive,
    mcp_get_file,
    mcp_put_file,
    mcp_clipboard_get,
    mcp_clipboard_set,
    mcp_preset_list,
    mcp_preset_run,
    mcp_debug_audit,
    mcp_preset_savings,
    mcp_system,
    mcp_transform,
    mcp_ssot_query,
    mcp_ssot_get,
)
from .reports import mcp_report
from .focus import mcp_focus
from .ssot import mcp_read_ssot, mcp_search_ssot, mcp_mddb_doc, mcp_query_ssot
from .context import mcp_context, mcp_session_summary
from .preprocess import mcp_preprocess
from .capture import (
    mcp_screenshot,
    mcp_window_list,
    mcp_clipboard_image_get,
)
from .ssot_edit import mcp_ssot_append

logger = logging.getLogger(__name__)


def handle_initialize(id_):
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mcp-debug", "version": "2"},
        },
    }


def handle_tools_list(id_):
    known = ", ".join(DEBUG_COMMANDS.keys())
    tools = [
        {
            "name": "mcp_debug",
            "description": f"Run a compact debug command on a host. Known commands: {known}",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "command": {"type": "string", "description": "Debug command, e.g. 'systemctl list-units'"},
                },
                "required": ["host", "command"],
            },
        },
        {
            "name": "mcp_raw",
            "description": "Run a raw command on a host with allowed prefixes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "command": {"type": "string", "description": "Raw shell command"},
                },
                "required": ["host", "command"],
            },
        },
        {
            "name": "mcp_stats",
            "description": "Compare raw and compact output for a command and report word/character savings.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "command": {"type": "string", "description": "Command to compare, e.g. 'df -h'"},
                },
                "required": ["host", "command"],
            },
        },
        {
            "name": "mcp_vet",
            "description": "Vet a candidate command on all hosts and optionally add it to the SSOT.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Candidate command to vet"},
                    "add": {"type": "boolean", "description": "Add to SSOT if all hosts pass", "default": False},
                },
                "required": ["command"],
            },
        },
        {
            "name": "mcp_savings",
            "description": "Compute live total raw/compact/savings across all debug commands on one or more hosts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "hosts": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(HOSTS.keys())},
                        "description": "Hosts to include (defaults to all)",
                    },
                },
            },
        },
        {
            "name": "mcp_diff",
            "description": "Run the same command on two hosts and return a unified diff.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to diff"},
                    "hosts": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(HOSTS.keys())},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Two hosts to compare",
                    },
                    "compact": {"type": "boolean", "description": "Use compact output for both hosts", "default": False},
                },
                "required": ["command", "hosts"],
            },
        },
        {
            "name": "mcp_logs",
            "description": "Tail a file or fetch journalctl logs for a service on a host.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "unit": {"type": "string", "description": "systemd unit for journalctl"},
                    "file": {"type": "string", "description": "File path for tail"},
                    "lines": {"type": "integer", "description": "Number of lines", "default": 50},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_net",
            "description": "Show listening sockets with ss -tlnp, optionally filtered by port.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "port": {"type": "integer", "description": "Optional port filter"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_env",
            "description": "Dump remote environment variables, optionally filtered by a substring.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "pattern": {"type": "string", "description": "Optional substring filter (case-insensitive)"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_gpu",
            "description": "Run nvidia-smi or rocm-smi on a host and return the output.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_health",
            "description": "Check that the mcp-debug binary exists and is reachable on a host. Fails fast if SSH is down.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_adaptive",
            "description": "Run a compact debug command and fall back to raw output when compact does not reduce size.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "command": {"type": "string", "description": "Debug command, e.g. 'df -h'"},
                },
                "required": ["host", "command"],
            },
        },
        {
            "name": "mcp_get_file",
            "description": "Fetch a remote file as base64 with size and truncation metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "path": {"type": "string", "description": "Remote file path to read"},
                    "max_bytes": {"type": "integer", "description": "Maximum bytes to read", "default": 65536},
                },
                "required": ["host", "path"],
            },
        },
        {
            "name": "mcp_put_file",
            "description": "Write base64 content to a remote path after allowlist vetting.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "path": {"type": "string", "description": "Remote file path to write"},
                    "content_base64": {"type": "string", "description": "Base64-encoded content"},
                    "mode": {"type": "string", "description": "File mode (octal)", "default": "644"},
                    "overwrite": {"type": "boolean", "description": "Allow overwriting existing file", "default": False},
                },
                "required": ["host", "path", "content_base64"],
            },
        },
        {
            "name": "mcp_clipboard_get",
            "description": "Read the host clipboard. Requires per-host clipboard opt-in.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_clipboard_set",
            "description": "Write text to the host clipboard. Requires per-host clipboard opt-in.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "text": {"type": "string", "description": "Text to copy"},
                },
                "required": ["host", "text"],
            },
        },
        {
            "name": "mcp_preset_list",
            "description": "List available multi-host diagnostic presets.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "mcp_preset_run",
            "description": "Run a named preset. Presets are multi-step, multi-host diagnostic routines.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "preset": {"type": "string", "description": "Preset name, e.g. 'quick-health'"},
                },
                "required": ["preset"],
            },
        },
        {
            "name": "mcp_debug_audit",
            "description": "Filter the live mcp_savings report for negative/failed commands, sorted by savings.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "hosts": {"type": "array", "items": {"type": "string"}, "description": "Hosts to audit (defaults to all)"},
                    "threshold": {"type": "number", "description": "Only return commands below this savings percentage (default 0.0)", "default": 0.0},
                },
            },
        },
        {
            "name": "mcp_preset_savings",
            "description": "Score a preset's message and payload savings compared to running each step separately.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "preset": {"type": "string", "description": "Preset name to score"},
                },
                "required": ["preset"],
            },
        },
        {
            "name": "mcp_system",
            "description": "Run an exact systemctl command on a host. Requires the command to start with 'systemctl'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Target host"},
                    "command": {"type": "string", "description": "Exact systemctl command, e.g. 'systemctl --user status redis.service'"},
                },
                "required": ["host", "command"],
            },
        },
        {
            "name": "mcp_transform",
            "description": "Transform a previous step or context value: filter, sort, capture, or pick.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": ["integer", "string"], "description": "Step index or '$captured' variable"},
                    "op": {"type": "string", "enum": ["filter", "sort", "capture", "pick"], "description": "Transform operation"},
                    "params": {"type": "object", "description": "Operation-specific parameters"},
                },
                "required": ["input", "op", "params"],
            },
        },
        {
            "name": "mcp_report",
            "description": "Generate a savings report in markdown, json, csv, or html from mcp_savings and optionally save it to reports/.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "hosts": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(HOSTS.keys())},
                        "description": "Hosts to include (defaults to all)",
                    },
                    "save": {"type": "boolean", "description": "Save the report to reports/mcp-savings-YYYY-MM-DD.{format}", "default": False},
                    "format": {"type": "string", "enum": ["markdown", "json", "csv", "html"], "description": "Output format", "default": "markdown"},
                },
            },
        },
        {
            "name": "mcp_read_ssot",
            "description": "Read the content of an SSOT file within the repository.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute path to the SSOT file"},
                    "limit": {"type": "integer", "description": "Maximum characters to return", "default": 20000},
                },
                "required": ["path"],
            },
        },
        {
            "name": "mcp_search_ssot",
            "description": "Search SSOT files using MDDB vector search with a local YAML keyword fallback.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language or keyword query"},
                    "collection": {"type": "string", "description": "MDDB collection to search", "default": "ssot-infrastructure"},
                    "limit": {"type": "integer", "description": "Maximum results", "default": 5},
                },
                "required": ["query"],
            },
        },
        {
            "name": "mcp_mddb_doc",
            "description": "Search for the most relevant SSOT document and return its full content. Uses MDDB if available, falls back to local search.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language or keyword query"},
                    "collection": {"type": "string", "description": "MDDB collection to search", "default": "ssot-infrastructure"},
                    "top_k": {"type": "integer", "description": "Number of full documents to return", "default": 1},
                    "read_limit": {"type": "integer", "description": "Maximum characters per document", "default": 20000},
                },
                "required": ["query"],
            },
        },
        {
            "name": "mcp_query_ssot",
            "description": "Find a relevant SSOT document and return a specific value or list at a dotted/integer path.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language or keyword query to locate the SSOT file"},
                    "path": {"type": "string", "description": "Direct relative path to the SSOT file"},
                    "key": {"type": "string", "description": "Dotted path inside the YAML, e.g. 'audits' or 'schedule.default.runs' or 'audits.0.name'"},
                    "limit": {"type": "integer", "description": "If the result is a list, return up to this many items", "default": 50},
                },
            },
        },
        {
            "name": "mcp_ssot_query",
            "description": "Search the SSOT registry for assets across all partitions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host (the mcp-debug server on that host reads its local chaba repo)"},
                    "q": {"type": "string", "description": "Optional keyword / id / name / path / purpose fragment. Omit to list assets."},
                    "type": {"type": "string", "enum": ["all", "ssot", "script", "service", "timer", "stack", "h3-app"], "description": "Filter by asset type", "default": "all"},
                    "by": {"type": "string", "enum": ["any", "id", "name", "path", "purpose", "label", "tags"], "description": "Fields to match against", "default": "any"},
                    "limit": {"type": "integer", "description": "Maximum results", "default": 5},
                    "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_ssot_get",
            "description": "Resolve a single SSOT/registry asset by id or path and return its metadata plus source SSOT content.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": list(HOSTS.keys()), "description": "Target host"},
                    "id": {"type": "string", "description": "Asset id"},
                    "path": {"type": "string", "description": "Asset path"},
                    "ssot_limit": {"type": "integer", "description": "Maximum characters of source SSOT to return", "default": 20000},
                },
            },
        },
        {
            "name": "mcp_context",
            "description": "Return relevant KB and SSOT files based on the active focus and an optional query.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional query to expand the active focus context"},
                    "top_k": {"type": "integer", "description": "Maximum number of results per category", "default": 10},
                },
            },
        },
        {
            "name": "mcp_session_summary",
            "description": "Return a structured summary of the active focus and recent sessions/decisions.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "mcp_preprocess",
            "description": "Ground a user request in the active focus and return a structured, unambiguous prompt.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "string", "description": "The user request to preprocess"},
                },
                "required": ["request"],
            },
        },
        {
            "name": "mcp_screenshot",
            "description": "Capture a screenshot on an allowed host and return it as base64 PNG.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": ["macbook", "kk-macbook", "tony_dell", "tony_omen"], "description": "Target host"},
                    "region": {"type": "object", "description": "Optional {x, y, width, height} crop"},
                    "format": {"type": "string", "enum": ["png"], "default": "png", "description": "Output format"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_window_list",
            "description": "Return a list of visible windows/apps on an allowed host.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": ["macbook", "kk-macbook", "tony_dell", "tony_omen"], "description": "Target host"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_clipboard_image_get",
            "description": "Return the image on an allowed host clipboard as base64 PNG.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": ["macbook", "kk-macbook", "tony_dell", "tony_omen"], "description": "Target host"},
                },
                "required": ["host"],
            },
        },
        {
            "name": "mcp_ssot_append",
            "description": "Append a new item to a whitelisted list section in a docs/ssot/ YAML file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "SSOT file path, e.g. docs/ssot/ssot.focus.current.yml"},
                    "section": {"type": "string", "enum": ["quick_wins", "history", "request_log", "subtasks", "improvements", "notes", "items", "services"], "description": "Top-level list section to append to"},
                    "item": {"type": "string", "description": "YAML snippet for the new list entry"},
                },
                "required": ["path", "section", "item"],
            },
        },
        {
            "name": "mcp_focus",
            "description": "Focus router. Modes: recommend, status, done, pre_action, safe_next, ready_queue, defer, resume, sweep, next, technical_decision, session_summary.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "string", "description": "User request for recommend/status/pre_action or defer reason"},
                    "mode": {"type": "string", "enum": ["recommend", "status", "done", "pre_action", "safe_next", "ready_queue", "defer", "resume", "sweep", "next", "technical_decision", "session_summary"], "default": "recommend", "description": "Focus mode"},
                    "resume_session": {"type": "string", "description": "Target session identifier for defer or resume"},
                    "reason": {"type": "string", "description": "Reason for deferring"},
                    "hold": {"type": "string", "description": "Label to hold during sweep"},
                    "bulk_session": {"type": "string", "description": "Session for bulk-deferred sweep candidates"},
                    "session_map": {"type": "object", "description": "Mapping of label/branch/default to session"},
                    "confirm": {"type": "boolean", "default": False, "description": "Confirm activation for mode=next"},
                    "decision": {"type": "object", "description": "Decision object for technical_decision mode"},
                    "summary": {"type": "object", "description": "Session summary object"},
                },
            },
        },
    ]
    return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}}


def handle_tools_call(id_, params):
    name = params.get("name")
    arguments = params.get("arguments", {})
    host = arguments.get("host")
    command = arguments.get("command")

    if name == "mcp_debug":
        if not host or not command:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and command are required"}}
        output = mcp_debug(host, command)
    elif name == "mcp_raw":
        if not host or not command:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and command are required"}}
        output = mcp_raw(host, command)
    elif name == "mcp_stats":
        if not host or not command:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and command are required"}}
        result = mcp_stats(host, command)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_vet":
        cmd = arguments.get("command")
        if not cmd:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "command is required"}}
        result = mcp_vet(cmd, add=arguments.get("add", False))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_savings":
        result = mcp_savings(arguments.get("hosts"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_diff":
        cmd = arguments.get("command")
        hosts = arguments.get("hosts", [])
        compact = arguments.get("compact", False)
        if not cmd or len(hosts) != 2:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "command and exactly 2 hosts are required"}}
        result = mcp_diff(cmd, hosts, compact)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_logs":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_logs(h, unit=arguments.get("unit"), file=arguments.get("file"), lines=arguments.get("lines", 50))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_net":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_net(h, port=arguments.get("port"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_env":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_env(h, pattern=arguments.get("pattern"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_gpu":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_gpu(h)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_health":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_health(h)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_adaptive":
        if not host or not command:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and command are required"}}
        output = mcp_adaptive(host, command)
    elif name == "mcp_get_file":
        p = arguments.get("path")
        if not host or not p:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and path are required"}}
        result = mcp_get_file(host, p, max_bytes=arguments.get("max_bytes"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_put_file":
        p = arguments.get("path")
        b = arguments.get("content_base64")
        if not host or not p or not b:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host, path, and content_base64 are required"}}
        result = mcp_put_file(host, p, b, mode=arguments.get("mode", "644"), overwrite=arguments.get("overwrite", False))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_clipboard_get":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_clipboard_get(h)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_clipboard_set":
        h = arguments.get("host")
        text = arguments.get("text")
        if not h or not text:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and text are required"}}
        result = mcp_clipboard_set(h, text)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_preset_list":
        result = mcp_preset_list()
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_preset_run":
        preset = arguments.get("preset")
        if not preset:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "preset is required"}}
        result = mcp_preset_run(preset)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_debug_audit":
        result = mcp_debug_audit(
            hosts=arguments.get("hosts"),
            threshold=float(arguments.get("threshold", 0.0)),
        )
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_preset_savings":
        preset = arguments.get("preset")
        if not preset:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "preset is required"}}
        result = mcp_preset_savings(preset)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_system":
        h = arguments.get("host")
        command = arguments.get("command")
        if not h or not command:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host and command are required"}}
        result = mcp_system(h, command)
        output = result
    elif name == "mcp_transform":
        result = mcp_transform(
            input=arguments.get("input"),
            op=arguments.get("op", "identity"),
            params=arguments.get("params", {}),
        )
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_report":
        result = mcp_report(arguments.get("hosts"), save=arguments.get("save", False), format=arguments.get("format", "markdown"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_read_ssot":
        result = mcp_read_ssot(path=arguments.get("path"), limit=arguments.get("limit", 20000))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_search_ssot":
        result = mcp_search_ssot(
            query=arguments.get("query"),
            collection=arguments.get("collection", "ssot-infrastructure"),
            limit=arguments.get("limit", 5),
        )
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_mddb_doc":
        result = mcp_mddb_doc(
            query=arguments.get("query"),
            collection=arguments.get("collection", "ssot-infrastructure"),
            top_k=arguments.get("top_k", 1),
            read_limit=arguments.get("read_limit", 20000),
        )
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_query_ssot":
        result = mcp_query_ssot(
            query=arguments.get("query"),
            path=arguments.get("path"),
            key=arguments.get("key"),
            limit=arguments.get("limit", 50),
        )
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_ssot_query":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_ssot_query(
            host=h,
            q=arguments.get("q"),
            type=arguments.get("type", "all"),
            by=arguments.get("by", "any"),
            limit=arguments.get("limit", 5),
            offset=arguments.get("offset", 0),
        )
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_ssot_get":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_ssot_get(
            host=h,
            id=arguments.get("id"),
            path=arguments.get("path"),
            ssot_limit=arguments.get("ssot_limit", 20000),
        )
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_context":
        result = mcp_context(
            query=arguments.get("query"),
            top_k=arguments.get("top_k", 10),
        )
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_session_summary":
        result = mcp_session_summary()
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_preprocess":
        result = mcp_preprocess(request=arguments.get("request"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_screenshot":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_screenshot(h, region=arguments.get("region"), fmt=arguments.get("format", "png"))
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_window_list":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_window_list(h)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_clipboard_image_get":
        h = arguments.get("host")
        if not h:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "host is required"}}
        result = mcp_clipboard_image_get(h)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_ssot_append":
        p = arguments.get("path")
        s = arguments.get("section")
        item = arguments.get("item")
        if not p or not s or item is None:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": "path, section, and item are required"}}
        result = mcp_ssot_append(p, s, item)
        output = json.dumps(result, separators=(",", ":"))
    elif name == "mcp_focus":
        result = mcp_focus(
            request=arguments.get("request"),
            mode=arguments.get("mode", "recommend"),
            decision=arguments.get("decision"),
            summary=arguments.get("summary"),
            resume_session=arguments.get("resume_session"),
            reason=arguments.get("reason"),
            hold=arguments.get("hold"),
            bulk_session=arguments.get("bulk_session"),
            session_map=arguments.get("session_map"),
            confirm=arguments.get("confirm", False),
        )
        output = json.dumps(result, separators=(",", ":"))
    else:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"unknown tool: {name}"}}

    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {"content": [{"type": "text", "text": output}]},
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            method = msg.get("method")
            id_ = msg.get("id")
            if method == "initialize":
                print(json.dumps(handle_initialize(id_)))
            elif method == "tools/list":
                print(json.dumps(handle_tools_list(id_)))
            elif method == "tools/call":
                print(json.dumps(handle_tools_call(id_, msg.get("params", {}))))
            elif "id" in msg:
                print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}))
            sys.stdout.flush()
        except json.JSONDecodeError as e:
            logger.error("invalid json: %s", e)


if __name__ == "__main__":
    main()

