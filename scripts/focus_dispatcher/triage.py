"""Focus triage and selection helpers."""
import sys
from pathlib import Path

import yaml

from .state import (
    INBOX_DIR,
    find_section,
    load_current,
    load_focus,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from focus_common import (
    active_branches, backlog_items, incomplete_subtasks, inbox_items, is_active,
    meets_safe_criteria, priority_value, triage_score,
)


def safe_to_dispatch(session=None):
    """Return the highest-scoring backlog or inbox item that is safe to run in parallel."""
    current = load_current()
    branch_set = active_branches(current)
    candidates = []

    for item in backlog_items(load_focus()):
        if not is_active(item) and not item.get("status") == "parked":
            continue
        if meets_safe_criteria(item, branch_set, session=session):
            item["__source"] = "backlog"
            candidates.append(item)

    for focus in inbox_items(INBOX_DIR):
        if meets_safe_criteria(focus, branch_set, session=session):
            focus["__source"] = str(focus.get("__file", ""))
            candidates.append(focus)

    if not candidates:
        return None
    candidates.sort(
        key=lambda it: (
            triage_score(it),
            priority_value(it),
            it.get("started", ""),
        ),
        reverse=True,
    )
    return candidates[0]


def next_from_active(doc):
    sections = doc.get("sections", [])
    candidates = []
    for sec in sections:
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if is_active(item) and incomplete_subtasks(item):
                    candidates.append((sec["title"], item))
    if not candidates:
        return None, None

    def sort_key(x):
        _, it = x
        return (priority_value(it), it.get("started", ""))

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def next_from_inbox():
    items = []
    if not INBOX_DIR.is_dir():
        return None
    for p in sorted(INBOX_DIR.glob("*.yml")):
        if p.name.startswith("TEMPLATE") or p.name.startswith("processed"):
            continue
        try:
            doc = yaml.safe_load(p.read_text())
        except yaml.YAMLError as e:
            print(f"warning: skipping invalid inbox {p}: {e}", file=sys.stderr)
            continue
        focus = doc.get("focus") or doc
        if not focus or not focus.get("label"):
            continue
        focus["__file"] = p
        items.append(focus)
    if not items:
        return None
    items.sort(key=lambda it: (priority_value(it), it.get("__file").stem), reverse=True)
    return items[0]


def next_from_backlog():
    doc = load_focus()
    section = find_section(doc.get("sections", []), "Backlog - Triage Queue")
    if not section:
        return None
    items = [i for i in section.get("items", []) if i.get("status") in ("pending", "not_started", "active")]
    if not items:
        return None
    for it in items:
        it["__triage_score"] = triage_score(it)
    items.sort(key=lambda it: (it.get("__triage_score", 0), priority_value(it), it.get("started", "")), reverse=True)
    return items[0]


def dispatchable_backlog():
    """Return backlog items with subagent.runnable == true and requires_approval == false."""
    doc = load_focus()
    section = find_section(doc.get("sections", []), "Backlog - Triage Queue")
    if not section:
        return []
    eligible = []
    for item in section.get("items", []):
        if item.get("status") not in ("pending", "not_started"):
            continue
        subagent = item.get("subagent", {})
        if subagent.get("runnable") and not subagent.get("requires_approval"):
            eligible.append(item)
    return eligible
