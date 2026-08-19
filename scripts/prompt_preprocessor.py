"""Prompt / command preprocessor for context and precision.

Read-only prototype that grounds a user request in active focus, quick wins,
and the focus decision tree, then emits a structured, unambiguous prompt.
"""
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from mcp_debug.focus import mcp_focus
from focus_common import QUICK_WIN_CUES
from focus_dispatcher.actions import suggest_intake


CONTINUE_CUES = ("continue", "next", "proceed", "go on", "do this", "do that")


ACTION_TOOL_MAP = {
    "active": ["mcp_focus"],
    "safe": ["mcp_focus", "mcp_debug"],
    "quick_win": ["mcp_focus", "mcp_debug"],
    "backlog": ["mcp_focus"],
    "inbox": ["save-to-focus"],
    "decompose": ["mcp_focus"],
}

CURRENT = REPO / "docs" / "ssot" / "ssot.focus.current.yml"
MCP_DEBUG = REPO / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.yml"


def _load_current():
    with open(CURRENT) as f:
        return yaml.safe_load(f) or {}


def _load_mcp_debug():
    with open(MCP_DEBUG) as f:
        return yaml.safe_load(f) or {}


def _allowed_prefixes(host=None):
    doc = _load_mcp_debug()
    base = doc.get("raw_commands", {}).get("allowed_prefixes", [])
    per_host = doc.get("raw_commands", {}).get("per_host", {})
    if host and host in per_host:
        return list(set(base + per_host[host].get("allowed_prefixes", [])))
    return base


def _active_focus_label(status):
    for k in ("branch", "shared"):
        if status.get("active", {}).get(k):
            return status["active"][k].get("label", "")
    return ""


def _active_subtask(status):
    # Prefer the subtask that is actually in progress; fall back to the first not-started one.
    for k in ("branch", "shared"):
        item = status.get("active", {}).get(k)
        if not item:
            continue
        for st in item.get("subtasks", []):
            if st.get("status") == "in_progress":
                return st.get("label", "")
    for k in ("branch", "shared"):
        item = status.get("active", {}).get(k)
        if not item:
            continue
        for st in item.get("subtasks", []):
            if st.get("status") == "not_started":
                return st.get("label", "")
    return ""


def preprocess(request):
    if not request or not request.strip():
        return {
            "ok": False,
            "error": "request is required",
        }

    status = mcp_focus(mode="status")
    current = _load_current()
    action, section, target, subtask = suggest_intake(request, current)

    active_label = _active_focus_label(status)
    active_subtask = _active_subtask(status)
    command = canonicalize_command(request)

    # If the request is a valid shell command, prefer command dispatch
    if command.get("ok"):
        action = "mcp_raw"
        inferred = command["canonical"]
        target = command["original"]
        suggested_tools = ["mcp_debug"]
    else:
        # Expand shorthand cues
        inferred = request.strip()
        req_lower = request.lower()
        # Quick-win cues take priority over "... this/that" continuation
        if any(c in req_lower for c in QUICK_WIN_CUES):
            action = "quick_win"
        elif any(c == req_lower for c in CONTINUE_CUES) or req_lower.endswith(" this") or req_lower.endswith(" that"):
            action = "active"
            inferred = f"Continue active focus: {active_label or 'unknown'}"
        elif req_lower.startswith("do "):
            inferred = f"{inferred} in the context of {active_label or 'active focus'}"
        suggested_tools = ACTION_TOOL_MAP.get(action, ["mcp_focus"])

    return {
        "ok": True,
        "request": request,
        "inferred_goal": inferred,
        "focus_classification": {
            "action": action,
            "section": section,
            "target": target,
            "subtask": subtask,
        },
        "context": {
            "active_focus": active_label,
            "active_subtask": active_subtask,
            "quick_wins": [q.get("label") for q in status.get("quick_wins", [])],
        },
        "suggested_tools": suggested_tools,
        "missing_info": [],
    }


COMMAND_ALIASES = {
    "reboot": "systemctl reboot",
    "shutdown": "systemctl poweroff",
    "ipconfig": "ip addr",
    "ifconfig": "ip addr",
    "netstat": "ss",
    "top": "top",
    "htop": "top",
    "vi": "cat",
    "vim": "cat",
    "nano": "cat",
    "less": "head",
    "more": "head",
    "pstree": "ps -ef --forest",
    "free -h": "free -h",
    "uptime": "uptime",
    "whoami": "whoami",
}


def canonicalize_command(command, host=None):
    if not command or not command.strip():
        return {"ok": False, "error": "command is required"}

    import shlex
    try:
        tokens = shlex.split(command.strip())
    except ValueError as e:
        return {"ok": False, "error": f"Failed to parse command: {e}"}

    if not tokens:
        return {"ok": False, "error": "empty command"}

    # Expand known aliases
    clean = command.strip().lower()
    base = clean.split(None, 1)[0]
    if clean in COMMAND_ALIASES:
        canonical = COMMAND_ALIASES[clean]
        tokens = shlex.split(canonical)
    elif base in COMMAND_ALIASES:
        rest = clean[len(base):].strip()
        canonical = (COMMAND_ALIASES[base] + " " + rest).strip()
        tokens = shlex.split(canonical)
    else:
        canonical = command.strip()

    allowed = _allowed_prefixes(host)
    if tokens[0] not in allowed:
        return {
            "ok": False,
            "error": f"Command prefix '{tokens[0]}' is not in the mcp_debug allowlist for host {host or 'global'}",
            "canonical": canonical,
            "original": command,
            "suggested_prefixes": [p for p in allowed if p.startswith(base[:3])][:5],
        }

    return {
        "ok": True,
        "canonical": canonical,
        "original": command,
        "host": host,
        "tool": "mcp_raw",
    }


if __name__ == "__main__":
    import json
    for r in sys.argv[1:] or ["next"]:
        print(json.dumps(preprocess(r), indent=2, default=str))
