"""Focus activation and intake actions."""
from datetime import datetime

import yaml

from mcp_debug.focus import log_decision

from .git import git_mv_inbox
from .state import (
    CURRENT,
    DECISIONS,
    FOCUS,
    INBOX_DIR,
    find_section,
    is_active,
    load_current,
    load_focus,
    save_current,
    save_focus,
    validate_current,
)


def make_focus_item(label, text, branch, priority, tags, subtasks, source=None, session=None):
    today = datetime.now().strftime("%Y-%m-%d")
    item = {
        "label": label,
        "text": text,
        "status": "active",
        "priority": priority,
        "started": today,
        "estimated_duration": "1 session",
        "tags": tags or ["focus"],
        "subtasks": subtasks or [],
        "request_log": [],
        "owner": "tony",
        "session": session or "",
        "locked": True,
        "lock_reason": "Activated as active focus",
    }
    if branch:
        item["branch"] = branch
    if source:
        item["source"] = source
    return item


def make_ready_safe_item(item, session=None):
    today = datetime.now().strftime("%Y-%m-%d")
    source = item.pop("__source", item.get("source", item.get("__file", "")))
    for key in ("__triage_score", "__file"):
        item.pop(key, None)
    ready = {
        "label": item.get("label"),
        "text": item.get("text", ""),
        "branch": item.get("branch", ""),
        "priority": item.get("priority", "medium"),
        "status": "ready",
        "queued_at": today,
        "tags": item.get("tags", []),
        "triage": item.get("triage", {}),
        "safe_to_parallel": item.get("safe_to_parallel", True),
        "subtasks": item.get("subtasks", []),
        "source": source,
        "owner": item.get("owner", "focus-dispatcher"),
        "session": session or item.get("session", ""),
        "locked": False,
        "lock_reason": "",
    }
    if item.get("job_lifecycle"):
        ready["job_lifecycle"] = item["job_lifecycle"]
    if item.get("estimated_duration"):
        ready["estimated_duration"] = item["estimated_duration"]
    return ready


def activate_inbox(inbox, park=False):
    doc = load_current()
    validate_current(doc)
    sections = doc.get("sections", [])
    branch = inbox.get("branch")
    if branch:
        section_title = "Active Branch Focus"
    else:
        section_title = "Active Shared Focus"
    section = find_section(sections, section_title)
    if section is None:
        raise RuntimeError(f"Section {section_title} not found in {CURRENT}")

    active_items = [it for it in section.get("items", []) if is_active(it)]
    if active_items:
        if not park:
            labels = ", ".join(it.get("label", "?") for it in active_items)
            raise RuntimeError(f"{section_title} already has active item(s): {labels}. Use --park to interrupt.")
        for item in active_items:
            item["status"] = "parked"
            item["parked"] = datetime.now().strftime("%Y-%m-%d")
            item.pop("completed", None)

    new_item = make_focus_item(
        inbox.get("label"),
        inbox.get("text", ""),
        branch,
        inbox.get("priority", "medium"),
        inbox.get("tags", []),
        inbox.get("subtasks", []),
        source=str(inbox.get("__file")),
    )
    section["items"].append(new_item)
    save_current(doc)
    validate_current(doc)
    target = git_mv_inbox(inbox["__file"])
    return section_title, new_item, str(target)


def suggest_intake(request, current_doc):
    req = request.lower()
    active = {}
    for sec in current_doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if not item or item.get("status") != "active":
                    continue
                active[sec.get("title")] = item

    for section, item in active.items():
        if item.get("label", "").lower() in req:
            return "active", section, item["label"], None
        for st in item.get("subtasks", []):
            if st.get("label", "").lower() in req:
                return "active", section, item["label"], st["label"]

    for cue in ("quick", "small", "fix", "tweak"):
        if cue in req:
            return "quick_win", None, None, None

    for cue in ("all", "focus", "continue"):
        if cue in req:
            return "active", None, None, None

    for cue in ("design", "workflow", "rebuild", "implement"):
        if cue in req:
            return "backlog", None, None, None

    return "inbox", None, None, None


def add_ready_safe(item, session=None):
    doc = load_current()
    validate_current(doc)
    section = find_section(doc.get("sections", []), "Ready (Safe)")
    if section is None:
        raise RuntimeError("Ready (Safe) section not found in ssot.focus.current.yml")
    new_item = make_ready_safe_item(item, session=session)
    section["items"].append(new_item)
    save_current(doc)
    validate_current(doc)
    return new_item


def handle_intake(request, dry_run=False):
    current_doc = load_current()
    focus_doc = load_focus()
    action, section, active_label, subtask = suggest_intake(request, current_doc)
    changed = []
    result = {"action": action}
    today = datetime.now().strftime("%Y-%m-%d")

    if action == "active":
        if section is None:
            section = "Active Shared Focus"
            sec = find_section(current_doc.get("sections", []), section)
            item = sec.get("items", [None])[0]
            active_label = item.get("label") if item else "active focus"
            subtask = None
        else:
            sec = find_section(current_doc.get("sections", []), section)
            for it in sec.get("items", []):
                if it.get("label") == active_label:
                    item = it
                    break
        if item:
            item.setdefault("request_log", []).append({
                "date": today,
                "request": request,
                "matched_to": subtask or active_label,
            })
        if not dry_run:
            save_current(current_doc)
            changed = [CURRENT]
        result["message"] = f"Intake: appended to active focus '{active_label}'"
    elif action == "quick_win":
        quick = {
            "label": request.strip()[:80],
            "text": request.strip(),
            "status": "completed",
            "priority": "medium",
            "tags": ["quick-win"],
        }
        sec = find_section(current_doc.get("sections", []), "Quick Wins")
        if not dry_run:
            sec["items"].append(quick)
            save_current(current_doc)
            changed = [CURRENT]
        result["message"] = "Intake: added quick win"
    elif action == "backlog":
        backlog_item = {
            "label": request.strip()[:80],
            "text": request.strip(),
            "status": "pending",
            "priority": "medium",
            "tags": ["intake"],
        }
        sec = find_section(focus_doc.get("sections", []), "Backlog - Triage Queue")
        if not dry_run:
            sec["items"].append(backlog_item)
            save_focus(focus_doc)
            changed = [FOCUS]
        result["message"] = "Intake: added to backlog"
    else:
        path = INBOX_DIR / f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}-intake.yml"
        doc = {
            "title": "Focus Inbox Item",
            "subtitle": f"Intake for: {request}",
            "focus": {
                "label": request.strip()[:80],
                "text": request.strip(),
                "status": "draft",
                "priority": "medium",
                "tags": ["intake"],
                "missing_info": ["What is the desired outcome?"],
            },
        }
        if not dry_run:
            INBOX_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False))
            changed = [path]
        result["message"] = f"Intake: saved inbox draft at {path}"

    matched_to = active_label or subtask or ""
    log_decision(request, action, matched_to, result["message"], "high", "focus-dispatcher", matched_to, dry_run=dry_run)
    if not dry_run:
        changed = list(set(changed + [DECISIONS]))

    return result, changed
