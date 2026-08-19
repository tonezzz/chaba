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


def _load_current():
    with open(CURRENT) as f:
        return yaml.safe_load(f) or {}


def _active_focus_label(status):
    for k in ("branch", "shared"):
        if status.get("active", {}).get(k):
            return status["active"][k].get("label", "")
    return ""


def _active_subtask(status):
    for k in ("branch", "shared"):
        item = status.get("active", {}).get(k)
        if not item:
            continue
        for st in item.get("subtasks", []):
            if st.get("status") in ("in_progress", "not_started"):
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

    # Expand shorthand cues
    inferred = request.strip()
    req_lower = request.lower()
    if any(c == req_lower for c in CONTINUE_CUES) or any(req_lower.endswith(c) for c in ("do this", "do that")):
        action = "active"
        inferred = f"Continue active focus: {active_label or 'unknown'}"
    elif any(c in req_lower for c in QUICK_WIN_CUES):
        action = "quick_win"
    elif inferred.lower().startswith("do "):
        inferred = f"{inferred} in the context of {active_label or 'active focus'}"

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
        "suggested_tools": ACTION_TOOL_MAP.get(action, ["mcp_focus"]),
        "missing_info": [],
    }


if __name__ == "__main__":
    import json
    for r in sys.argv[1:] or ["next"]:
        print(json.dumps(preprocess(r), indent=2, default=str))
