"""Shared, state-free focus model helpers.

Used by both mcp_debug/focus.py (mcp_focus) and focus_dispatcher/triage.py.
"""

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parent.parent
CURRENT = REPO / "docs" / "ssot" / "ssot.focus.current.yml"
ACTIVE = REPO / "docs" / "ssot" / "ssot.focus.current.active.yml"
BACKLOG = REPO / "docs" / "ssot" / "ssot.focus.current.backlog.yml"
FOCUS = REPO / "docs" / "ssot" / "ssot.focus.yml"


def load_active():
    return load_yaml(ACTIVE)


def save_active(doc):
    with open(ACTIVE, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def load_backlog():
    return load_yaml(BACKLOG)


def save_backlog(doc):
    with open(BACKLOG, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


PRIORITY = {"high": 3, "medium": 2, "low": 1}
QUICK_WIN_CUES = ("fix", "tweak", "small", "quick", "minor")
BACKLOG_CUES = ("design", "workflow", "rebuild", "implement", "refactor")


def load_yaml(path):
    """Load a YAML file and return the parsed document."""
    with open(path) as f:
        return yaml.safe_load(f)


def find_section(sections, title):
    """Return the first section with the given title, or None."""
    for sec in sections:
        if sec.get("title") == title:
            return sec
    return None


def priority_value(item):
    return PRIORITY.get(item.get("priority", "medium"), 2)


def triage_score(item):
    triage = item.get("triage") or {}
    if not triage:
        # Fall back to priority-based score so items without explicit triage still sort
        return round(priority_value(item) * 2.5, 2)
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


def active_branch_set(active_map):
    """Return a set of branches for an active-map dict from active_items()."""
    branches = set()
    for it in active_map.values():
        if it:
            branches.add(it.get("branch", ""))
    return branches


def incomplete_subtasks(item):
    for st in item.get("subtasks", []):
        if st.get("status") != "completed":
            return True
    return False


def get_ownership(item):
    """Normalize the ownership/lock fields on an item."""
    ownership = item.get("ownership") or {}
    return {
        "owner": ownership.get("owner") if ownership.get("owner") is not None else item.get("owner", ""),
        "session": ownership.get("session") if ownership.get("session") is not None else item.get("session", ""),
        "locked": bool(ownership.get("locked") if ownership.get("locked") is not None else item.get("locked", False)),
        "lock_reason": ownership.get("lock_reason") if ownership.get("lock_reason") is not None else item.get("lock_reason", ""),
    }


def _session_matches(item, session):
    """Return True if the item's owner/session is empty or matches the session."""
    o = get_ownership(item)
    # Unowned items are always safe; only reject if an owner/session is set and
    # it does not match the current session.
    if not o["session"] and not o["owner"]:
        return True
    if not session:
        return False
    if o["session"] and o["session"] != session:
        return False
    if o["owner"] and o["owner"] != session:
        return False
    return True


def _subagent_dispatchable(subagent, allowed_hosts=("tony_dell", "local", "macbook")):
    """Return True if a subagent block is runnable on one of the allowed hosts."""
    if not subagent:
        return False
    if not subagent.get("runnable"):
        return False
    if subagent.get("requires_approval"):
        return False
    host = subagent.get("host", "tony_dell")
    return host in allowed_hosts


def meets_safe_criteria(item, active_branch_set, session=None):
    safe = item.get("safe_to_parallel")
    if safe is False:
        return False
    if item.get("missing_info"):
        return False
    subagent = item.get("subagent") or {}
    if not _subagent_dispatchable(subagent):
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
    if not _session_matches(item, session):
        return False
    return True


def safe_to_parallel_reason(item, active_branch_set, session=None):
    """Return (is_safe, reason) for an item."""
    if not item:
        return False, "empty item"
    safe = item.get("safe_to_parallel")
    if safe is False:
        return False, "explicitly marked not safe"
    if item.get("missing_info"):
        return False, "missing_info not empty"
    subagent = item.get("subagent") or {}
    if not subagent:
        return False, "missing subagent block for dispatch"
    if not subagent.get("runnable"):
        return False, "subagent.runnable is not true"
    if subagent.get("requires_approval"):
        return False, "requires user approval"
    host = subagent.get("host", "tony_dell")
    if host not in ("tony_dell", "local", "macbook"):
        return False, f"subagent.host {host} is not an allowed dispatch host"
    triage = item.get("triage") or {}
    try:
        complication = float(triage.get("complication", 10))
    except (TypeError, ValueError):
        complication = 10
    if complication > 4:
        return False, "complication above 4"
    if item.get("branch", "") in active_branch_set and item.get("branch"):
        return False, "branch conflicts with active focus"
    o = get_ownership(item)
    if o["locked"]:
        if session is None:
            return False, "locked by another session"
        if o["session"] and o["session"] != session:
            return False, "locked for a different session"
        if o["owner"] and o["owner"] != session:
            return False, "owned by a different session"
    elif o["owner"] or o["session"]:
        if session is None:
            return False, "has owner/session without a current session"
        if o["session"] and o["session"] != session:
            return False, "session does not match"
        if o["owner"] and o["owner"] != session:
            return False, "owner does not match"
    return True, "meets safe-to-parallel criteria"


def active_items(active_doc, backlog_doc=None):
    """Extract active foci, quick wins, hand-off queue, and ready-safe.

    active_doc contains the Active Shared Focus and Active Branch Focus sections.
    If backlog_doc is supplied, Quick Wins/Hand-off Queue/Ready (Safe) are read
    from it; otherwise they are taken from active_doc for backward compatibility.
    """
    active = {}
    quick_wins = []
    hand_off_queue = []
    ready_safe = []
    source = backlog_doc if backlog_doc is not None else active_doc
    for sec in source.get("sections", []):
        title = sec.get("title", "")
        if title == "Quick Wins":
            quick_wins = [i for i in sec.get("items", [])]
        elif title == "Hand-off Queue":
            hand_off_queue = [i for i in sec.get("items", [])]
        elif title == "Ready (Safe)":
            ready_safe = [i for i in sec.get("items", [])]
    for sec in active_doc.get("sections", []):
        title = sec.get("title", "")
        if title in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if not is_active(item):
                    continue
                if title == "Active Shared Focus":
                    active["shared"] = item
                else:
                    active["branch"] = item
    return active, quick_wins, hand_off_queue, ready_safe


def quick_wins(doc):
    """Return the Quick Wins section from a current focus document."""
    for sec in doc.get("sections", []):
        if sec.get("title") == "Quick Wins":
            return [i for i in sec.get("items", [])]
    return []


def hand_off_queue(doc):
    for sec in doc.get("sections", []):
        if sec.get("title") == "Hand-off Queue":
            return [i for i in sec.get("items", [])]
    return []


def backlog_items(focus_doc, section_title="Backlog - Triage Queue"):
    section = find_section(focus_doc.get("sections", []), section_title)
    if not section:
        return []
    return [
        i for i in section.get("items", [])
        if i and i.get("status") not in ("completed", "archived")
    ]


def inbox_items(inbox_dir, with_file=True):
    """Return unprocessed focus-inbox items."""
    items = []
    inbox_path = Path(inbox_dir)
    if not inbox_path.is_dir():
        return items
    for p in sorted(inbox_path.glob("*.yml")):
        if p.name.startswith("TEMPLATE") or p.name == "processed":
            continue
        try:
            doc = yaml.safe_load(p.read_text())
        except yaml.YAMLError:
            continue
        focus = doc.get("focus") or doc
        if not focus or not focus.get("label"):
            continue
        if with_file:
            focus["__file"] = p
        items.append(focus)
    return items


def sweep_candidates(current_doc, backlog, inbox, active=None):
    """Combine active, parked, backlog, inbox, and deferred-subtask candidates."""
    active = active or {}
    candidates = []
    seen = set()
    # Current sections (active and parked)
    for sec in current_doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if not item or not item.get("label"):
                    continue
                seen.add(item.get("label"))
                candidates.append({
                    "label": item.get("label"),
                    "text": item.get("text", ""),
                    "status": item.get("status"),
                    "priority": item.get("priority", "medium"),
                    "branch": item.get("branch"),
                    "score": triage_score(item),
                    "source": item.get("source", "ssot.focus.current.active.yml"),
                    "why": "current " + sec.get("title", "").lower().replace(" focus", ""),
                })
    # Backlog + parked
    for item in backlog:
        label = item.get("label")
        if not label or label in seen:
            continue
        seen.add(label)
        candidates.append({
            "label": label,
            "text": item.get("text", ""),
            "status": item.get("status"),
            "priority": item.get("priority", "medium"),
            "branch": item.get("branch"),
            "score": triage_score(item),
            "source": item.get("source", "ssot.focus.yml"),
            "why": "backlog" if item.get("status") not in ("parked",) else "parked",
        })
    # Inbox (not yet processed)
    for item in inbox:
        label = item.get("label")
        if not label or label in seen:
            continue
        seen.add(label)
        candidates.append({
            "label": label,
            "text": item.get("text", ""),
            "status": item.get("status", "pending"),
            "priority": item.get("priority", "medium"),
            "branch": item.get("branch"),
            "score": triage_score(item),
            "source": str(item.get("__file", "")),
            "why": "inbox",
        })
    # Active focus deferred subtasks
    for key in ("branch", "shared"):
        it = active.get(key)
        if not it:
            continue
        for st in it.get("subtasks", []):
            if st.get("status") == "deferred":
                label = st.get("label", "")
                if label and label not in seen:
                    seen.add(label)
                    candidates.append({
                        "label": label,
                        "text": it.get("text", ""),
                        "status": "deferred",
                        "priority": it.get("priority", "medium"),
                        "branch": it.get("branch"),
                        "score": triage_score(it),
                        "source": it.get("source", ""),
                        "why": f"deferred subtask of {it.get('label')}",
                    })
    candidates.sort(key=lambda x: (x["score"], priority_value(x), x["label"]), reverse=True)
    return candidates


def ready_safe_items(active, backlog, inbox, session=None):
    """Return all focus candidates that are safe to run in parallel, sorted by score."""
    candidates = []
    branch_set = active_branch_set(active)
    for source, pool in (("backlog", backlog), ("inbox", inbox)):
        for item in pool:
            if not item or item.get("status") in ("completed", "archived", "draft"):
                continue
            if meets_safe_criteria(item, branch_set, session=session):
                candidates.append({
                    "label": item.get("label", ""),
                    "branch": item.get("branch", ""),
                    "priority": item.get("priority", "medium"),
                    "triage_score": triage_score(item),
                    "source": source,
                    "safe_to_parallel": item.get("safe_to_parallel"),
                })
    candidates.sort(key=lambda i: (i["triage_score"], priority_value(i), i.get("started", "")), reverse=True)
    return candidates
