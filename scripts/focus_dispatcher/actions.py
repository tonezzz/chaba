"""Focus activation and intake actions."""
import sys
from datetime import datetime
from pathlib import Path

import yaml

from .git import git_mv_inbox
from .log import log_decision
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

# focus_common lives in scripts/ (parent of this package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from focus_common import (
    active_items as _active_items_map,
    backlog_items as _backlog_items,
    inbox_items as _inbox_items,
    priority_value,
    triage_score,
    sweep_candidates,
)


def make_focus_item(label, text, branch, priority, tags, subtasks, source=None, session=None, estimated_duration=None, job_lifecycle=None):
    today = datetime.now().strftime("%Y-%m-%d")
    item = {
        "label": label,
        "text": text,
        "status": "active",
        "priority": priority,
        "started": today,
        "estimated_duration": estimated_duration or "1 session",
        "tags": tags or ["focus"],
        "subtasks": subtasks or [],
        "request_log": [],
        "ownership": {
            "owner": "tony",
            "session": session or "",
            "locked": True,
            "lock_reason": "Activated as active focus",
        },
    }
    if job_lifecycle:
        item["job_lifecycle"] = job_lifecycle
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


def activate_inbox(inbox, park=False, dry_run=False):
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
        estimated_duration=inbox.get("estimated_duration"),
        job_lifecycle=inbox.get("job_lifecycle"),
    )
    section["items"].append(new_item)
    if dry_run:
        return section_title, new_item, str(inbox.get("__file", ""))
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


def _is_focus_complete(it):
    if not it:
        return True
    if it.get("status") == "completed":
        return True
    for st in it.get("subtasks", []):
        if st.get("status") not in ("completed", "deferred"):
            return False
    return True


def activate_candidate(candidate, dry_run=False):
    """Move a candidate (backlog, inbox, or parked current item) into the active branch focus."""
    today = datetime.now().strftime("%Y-%m-%d")
    current_doc = load_current()
    focus_doc = load_focus()
    focus_section = find_section(focus_doc.get("sections", []), "Backlog - Triage Queue")
    label = candidate.get("label", "")
    source = candidate.get("source", "")
    if not label:
        return None

    # Already in current active/parked sections
    for sec in current_doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if item and item.get("label") == label:
                    if sec.get("title") == "Active Branch Focus":
                        branch_sec = find_section(current_doc.get("sections", []), "Active Branch Focus")
                        if any(i.get("label") != label and i.get("status") == "active" for i in branch_sec.get("items", [])):
                            return None
                    item["status"] = "active"
                    item["started"] = today
                    if "parked" in item:
                        item["previous_status"] = item.pop("parked")
                    item.pop("deferred", None)
                    if not dry_run:
                        save_current(current_doc)
                    return item

    # Backlog in ssot.focus.yml
    if "ssot.focus.yml" in source:
        if focus_section:
            for i, item in enumerate(list(focus_section.get("items", []))):
                if item and item.get("label") == label:
                    if not dry_run:
                        focus_section["items"].pop(i)
                    item["status"] = "active"
                    item["started"] = today
                    item.pop("parked", None)
                    item.pop("deferred", None)
                    branch_sec = find_section(current_doc.get("sections", []), "Active Branch Focus")
                    if branch_sec:
                        if not dry_run:
                            branch_sec["items"].append(item)
                        else:
                            branch_sec["items"] = branch_sec.get("items", []) + [item]
                    if not dry_run:
                        save_focus(focus_doc)
                        save_current(current_doc)
                    return item
        return None

    # Focus-inbox file (not already processed)
    if "focus-inbox" in source and "processed" not in source:
        p = Path(source)
        if p.exists():
            doc = yaml.safe_load(p.read_text()) or {}
            focus = doc.get("focus") or doc
            focus["status"] = "active"
            focus["started"] = today
            focus.pop("deferred_at", None)
            focus.pop("deferred_session", None)
            focus.pop("deferred_reason", None)
            if not dry_run:
                processed_dir = INBOX_DIR / "processed"
                processed_dir.mkdir(exist_ok=True)
                new_path = processed_dir / p.name
                p.rename(new_path)
                if "focus" in doc:
                    doc["focus"] = focus
                else:
                    doc = focus
                with open(new_path, "w") as f:
                    yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)
                focus["source"] = str(new_path)
            branch_sec = find_section(current_doc.get("sections", []), "Active Branch Focus")
            if branch_sec:
                if not dry_run:
                    branch_sec["items"].append(focus)
                else:
                    branch_sec["items"] = branch_sec.get("items", []) + [focus]
            if not dry_run:
                save_current(current_doc)
            return focus
        return None

    return None


def _candidate_session(candidate):
    return (candidate.get("deferred_session") or candidate.get("resume_session") or "").strip().lower()


def activate_next(resume_session=None, dry_run=False):
    """Activate the highest-priority parked/deferred/draft/pending focus."""
    current_doc = load_current()
    active_map, _, _, _ = _active_items_map(current_doc)

    for key in ("branch", "shared"):
        it = active_map.get(key)
        if it and not _is_focus_complete(it):
            return {"ok": False, "error": f"Active {key} focus not complete: {it.get('label')}"}

    backlog = _backlog_items(load_focus())
    inbox = _inbox_items(INBOX_DIR)
    candidates = [
        c for c in sweep_candidates(current_doc, backlog, inbox, active=active_map)
        if c.get("status") in ("parked", "deferred", "draft", "pending")
    ]

    if resume_session:
        resume_session = resume_session.strip().lower()
        candidates = [c for c in candidates if _candidate_session(c) == resume_session]

    candidates.sort(key=lambda x: (priority_value(x), triage_score(x), x["label"]), reverse=True)

    if not candidates:
        return {"ok": True, "next": None, "reason": "No parked or deferred foci to process."}

    chosen = candidates[0]
    score = triage_score(chosen)
    chosen["confidence_score"] = round(score / 10, 2)
    if score >= 7:
        confidence_level = "high"
    elif score >= 4:
        confidence_level = "medium"
    else:
        confidence_level = "low"

    activated = activate_candidate(chosen, dry_run=dry_run)
    if not activated:
        return {"ok": False, "error": f"Could not activate {chosen.get('label')} because another focus is active", "next": chosen}

    return {
        "ok": True,
        "next": chosen,
        "activated": True,
        "recommendation": {
            "action": "next",
            "target": chosen.get("label"),
            "confidence": confidence_level,
            "confidence_score": chosen["confidence_score"],
            "reasoning": f"Activated the highest-priority parked/deferred focus: {chosen.get('label')}.",
            "next_prompt": f"Start working on {chosen.get('label')} or defer it.",
        },
    }


def advance_focus(resume_session=None, dry_run=False):
    """If the active focus is complete (or none), archive it and activate the next one."""
    from .history import archive_completed

    if not dry_run:
        archive_completed()
    return activate_next(resume_session=resume_session, dry_run=dry_run)


def next_focus(resume_session=None, dry_run=False):
    """Activate the next focus (will fail if another active focus exists)."""
    return activate_next(resume_session=resume_session, dry_run=dry_run)


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
