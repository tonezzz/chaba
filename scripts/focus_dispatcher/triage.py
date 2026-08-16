"""Focus triage and selection helpers."""
import sys

import yaml

from .state import (
    INBOX_DIR,
    PRIORITY,
    find_section,
    incomplete_subtasks,
    is_active,
    load_focus,
)


def priority_value(item):
    return PRIORITY.get(item.get("priority", "medium"), 2)


def triage_score(item):
    triage = item.get("triage", {})
    if not triage:
        return 0.0
    try:
        urgency = float(triage.get("urgency", 0))
        importance = float(triage.get("importance", 0))
        complication = float(triage.get("complication", 0))
    except (TypeError, ValueError):
        return 0.0
    return round(urgency * 0.4 + importance * 0.35 + (10 - complication) * 0.25, 2)


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
