"""Shared, state-free focus model helpers.

Used by both mcp_debug/focus.py (mcp_focus) and focus_dispatcher/triage.py.
"""

PRIORITY = {"high": 3, "medium": 2, "low": 1}
QUICK_WIN_CUES = ("fix", "tweak", "small", "quick", "minor")
BACKLOG_CUES = ("design", "workflow", "rebuild", "implement", "refactor")


def priority_value(item):
    return PRIORITY.get(item.get("priority", "medium"), 2)


def triage_score(item):
    triage = item.get("triage") or {}
    if not triage:
        return 0.0
    try:
        urgency = float(triage.get("urgency", 0))
        importance = float(triage.get("importance", 0))
        complication = float(triage.get("complication", 0))
    except (TypeError, ValueError):
        return 0.0
    return round(urgency * 0.4 + importance * 0.35 + (10 - complication) * 0.25, 2)


def is_active(item):
    return bool(item) and item.get("status") == "active"


def active_branches(doc):
    branches = set()
    for sec in doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if is_active(item):
                    branches.add(item.get("branch", ""))
    return branches


def incomplete_subtasks(item):
    for st in item.get("subtasks", []):
        if st.get("status") != "completed":
            return True
    return False


def meets_safe_criteria(item, active_branch_set):
    safe = item.get("safe_to_parallel")
    if safe is False:
        return False
    if safe is True:
        return True
    if item.get("missing_info"):
        return False
    if item.get("subagent", {}).get("requires_approval"):
        return False
    triage = item.get("triage") or {}
    try:
        complication = float(triage.get("complication", 10))
    except (TypeError, ValueError):
        complication = 10
    if complication > 4:
        return False
    if item.get("branch", "") in active_branch_set and item.get("branch"):
        return False
    return True
