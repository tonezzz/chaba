"""Focus history and archiving helpers."""
from datetime import datetime

from .state import (
    CURRENT,
    FOCUS,
    find_section,
    is_completed,
    load_current,
    load_focus,
    save_current,
    save_focus,
)


def _outcome_from_item(item):
    completed = [s.get("label") for s in item.get("subtasks", []) if s.get("status") == "completed"]
    if completed:
        return "Completed subtasks: " + ", ".join(completed)
    return "Completed"


def _history_tags(item):
    tags = list(item.get("tags", []))
    if "completed" not in tags:
        tags.append("completed")
    return tags


def _add_to_history(history, item):
    labels = {h.get("label") for h in history.get("items", [])}
    if item.get("label") in labels:
        return
    history_item = {
        "label": item.get("label"),
        "text": item.get("text", ""),
        "date": item.get("completed") or datetime.now().strftime("%Y-%m-%d"),
        "duration": item.get("estimated_duration", "1 session"),
        "outcome": _outcome_from_item(item),
        "tags": _history_tags(item),
    }
    history["items"].append(history_item)


def _archive_section(current_doc, focus_doc, title):
    changed = []
    focus_sections = focus_doc.get("sections", [])
    history = find_section(focus_sections, "Focus History")
    if history is None:
        history = {"title": "Focus History", "icon": "history", "layout": "timeline", "items": []}
        focus_sections.append(history)

    # Archive from .current first, then the full focus file
    for doc, path in ((current_doc, CURRENT), (focus_doc, FOCUS)):
        sections = doc.get("sections", [])
        section = find_section(sections, title)
        if section is None:
            continue
        kept = []
        for item in section.get("items", []):
            if is_completed(item):
                _add_to_history(history, item)
                changed.append(path)
            else:
                kept.append(item)
        section["items"] = kept
    return changed


def archive_completed():
    current_doc = load_current()
    focus_doc = load_focus()
    changed = []
    changed += _archive_section(current_doc, focus_doc, "Active Shared Focus")
    changed += _archive_section(current_doc, focus_doc, "Active Branch Focus")
    if changed:
        save_current(current_doc)
        save_focus(focus_doc)
    return list(set(changed))
