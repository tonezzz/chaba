"""Session summary automation.

Reads active focus, recent sessions, and decisions; emits a structured summary
suitable for KB review and auto-kb input.
"""
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ACTIVE = REPO / "docs" / "ssot" / "ssot.focus.current.active.yml"
SESSIONS = REPO / "docs" / "ssot" / "ssot.focus.sessions.yml"
DECISIONS = REPO / "docs" / "ssot" / "ssot.focus.decisions.yml"


def _load(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _active_focus(doc):
    for sec in doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if item and item.get("status") == "active":
                    return item
    return {}


def _recent_sessions(doc, limit=3):
    return (doc.get("sessions", []) or [])[-limit:]


def _recent_decisions(doc, limit=5):
    return (doc.get("decisions", []) or [])[-limit:]


def session_summary():
    current = _load(ACTIVE)
    sessions = _load(SESSIONS)
    decisions = _load(DECISIONS)

    focus = _active_focus(current)
    recent_sessions = _recent_sessions(sessions)
    recent_decisions = _recent_decisions(decisions)

    subtasks = [
        {
            "label": s.get("label"),
            "status": s.get("status"),
            "completed_at": s.get("completed_at"),
        }
        for s in focus.get("subtasks", [])
    ]

    summary = {
        "ok": True,
        "generated": str(Path(__file__).stat().st_mtime)[:19],
        "active_focus": {
            "label": focus.get("label"),
            "branch": focus.get("branch"),
            "priority": focus.get("priority"),
            "status": focus.get("status"),
        },
        "subtasks": subtasks,
        "recent_sessions": [
            {
                "focus": s.get("focus"),
                "next_action": s.get("next_action"),
                "date": s.get("date"),
            }
            for s in recent_sessions
        ],
        "recent_decisions": [
            {
                "title": d.get("title"),
                "topic": d.get("topic"),
                "decision": d.get("decision"),
            }
            for d in recent_decisions
        ],
        "kb_candidates": [focus.get("label")] + [s.get("focus") for s in recent_sessions if s.get("focus")],
    }
    return summary


if __name__ == "__main__":
    print(json.dumps(session_summary(), indent=2, default=str))
