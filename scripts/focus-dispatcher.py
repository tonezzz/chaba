#!/usr/bin/env python3
"""focus-dispatcher: pick the next active or inbox focus, archive completed, and prepare a prompt."""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from mcp_debug.focus import log_decision

REPO = Path(__file__).resolve().parent.parent
CURRENT = REPO / "docs" / "ssot" / "ssot.focus.current.yml"
FOCUS = REPO / "docs" / "ssot" / "ssot.focus.yml"
DECISIONS = REPO / "docs" / "ssot" / "ssot.focus.decisions.yml"
INBOX_DIR = REPO / "docs" / "ssot" / "focus-inbox"
PROCESSED_DIR = INBOX_DIR / "processed"
REPORTS_DIR = REPO / "reports"
NEXT_FOCUS_MD = REPORTS_DIR / "NEXT_FOCUS.md"
SUBAGENT_CONTRACT_MD = REPORTS_DIR / "SUBAGENT_CONTRACT.md"

PRIORITY = {"high": 3, "medium": 2, "low": 1}


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


def is_active(item):
    status = item.get("status", "")
    return status in ("active", "in_progress", "not_started")


def is_parked(item):
    return item.get("status", "") == "parked"


def is_completed(item):
    return item.get("status", "") == "completed"


def incomplete_subtasks(item):
    return [s for s in item.get("subtasks", []) if s.get("status") != "completed"]


def load_current():
    with open(CURRENT) as f:
        return yaml.safe_load(f)


def load_focus():
    with open(FOCUS) as f:
        return yaml.safe_load(f)


def save_current(doc):
    with open(CURRENT, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def save_focus(doc):
    with open(FOCUS, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def find_section(sections, title):
    for sec in sections:
        if sec.get("title") == title:
            return sec
    return None


def validate_current(doc=None):
    if doc is None:
        doc = load_current()
    validation = doc.get("validation", {})
    limits = {
        "Active Shared Focus": validation.get("max_active_shared_focus", 1),
        "Active Branch Focus": validation.get("max_active_branch_focus", 1),
    }
    for section_title, limit in limits.items():
        sec = find_section(doc.get("sections", []), section_title)
        if sec is None:
            continue
        active_count = sum(1 for it in sec.get("items", []) if is_active(it))
        if active_count > limit:
            labels = ", ".join(it.get("label", "?") for it in sec.get("items", []) if is_active(it))
            raise RuntimeError(f"{section_title} has {active_count} active items (limit {limit}): {labels}")
    return True


def git_mv_inbox(inbox_path):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    target = PROCESSED_DIR / inbox_path.name
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(inbox_path)],
        cwd=REPO,
        capture_output=True,
    ).returncode == 0
    if tracked:
        subprocess.run(
            ["git", "mv", str(inbox_path), str(target)],
            cwd=REPO,
            check=True,
        )
    else:
        shutil.move(str(inbox_path), str(target))
        subprocess.run(
            ["git", "add", str(target)],
            cwd=REPO,
            check=True,
        )
    return target


def make_focus_item(label, text, branch, priority, tags, subtasks, source=None):
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
    }
    if branch:
        item["branch"] = branch
    if source:
        item["source"] = source
    return item


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


def _is_allowed_staged_path(path):
    rel = Path(path).relative_to(REPO)
    if path in (str(CURRENT), str(FOCUS)):
        return True
    inbox_rel = Path("docs/ssot/focus-inbox")
    try:
        rel.relative_to(inbox_rel)
        return True
    except ValueError:
        pass
    return False


def git_commit(changed_paths, message):
    if not changed_paths:
        return
    unique_paths = sorted(set(str(p) for p in changed_paths))
    subprocess.run(["git", "add"] + unique_paths, cwd=REPO, check=True)
    diff = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip().splitlines()
    for name in diff:
        if not _is_allowed_staged_path(REPO / name):
            print(f"Refusing to commit: unexpected staged file {name}", file=sys.stderr)
            subprocess.run(["git", "reset", "HEAD"], cwd=REPO, check=True)
            return
    if not diff:
        return
    subprocess.run(["git", "commit", "-m", message], cwd=REPO, check=True)
    if os.environ.get("FOCUS_DISPATCHER_PUSH") == "1":
        subprocess.run(["git", "push"], cwd=REPO, check=True)


def generate_prompt(title, item, source):
    label = item.get("label", "Unknown")
    text = item.get("text", "")
    branch = item.get("branch")
    subtasks = item.get("subtasks", [])
    incomplete = incomplete_subtasks(item)

    lines = [
        f"# NEXT FOCUS: {label}",
        "",
        f"**Section:** {title}",
        "",
        f"**Branch:** {branch or 'shared'}",
        "",
        f"**Priority:** {item.get('priority', 'medium')}",
        "",
        "## Description",
        "",
        text.strip() if isinstance(text, str) and text.strip() else "(no description)",
        "",
        "## Incomplete subtasks",
        "",
    ]
    if incomplete:
        for st in incomplete:
            lines.append(f"- [ ] {st.get('label', st)}")
    else:
        lines.append("- No tracked subtasks")
    lines.append("")
    if subtasks:
        lines.append("## All subtasks")
        lines.append("")
        for st in subtasks:
            mark = "x" if st.get("status") == "completed" else " "
            lines.append(f"- [{mark}] {st.get('label', st)}")
        lines.append("")

    if source:
        lines.append(f"**Source:** {source}")
        lines.append("")

    lines.append("## Instructions for the assistant")
    lines.append("")
    lines.append("1. Work only inside this focus unless the user asks otherwise.")
    lines.append("2. Mark each subtask completed in `docs/ssot/ssot.focus.current.yml` as you finish it.")
    lines.append("3. When the focus is complete, update `docs/ssot/ssot.focus.yml` history and run the focus-dispatcher again.")
    lines.append("")

    return "\n".join(lines)


def generate_suggestion_prompt(item):
    label = item.get("label", "Unknown")
    text = item.get("text", "")
    lines = [
        "# NO ACTIVE FOCUS — SUGGESTED BACKLOG ITEM",
        "",
        f"**Suggested:** {label}",
        f"**Priority:** {item.get('priority', 'medium')}",
        "",
        "## Description",
        "",
        text.strip() if isinstance(text, str) and text.strip() else "(no description)",
        "",
        "## Instructions",
        "1. This item is in the Backlog - Triage Queue; it is NOT activated.",
        "2. To activate it, run `python3 scripts/focus-dispatcher.py --inbox <path>` or update `ssot.focus.current.yml` manually.",
        "3. Otherwise, continue with any active focus or quick win.",
    ]
    return "\n".join(lines)


def generate_subagent_contract(title, item, source):
    prompt = generate_prompt(title, item, source)
    notes = [
        "",
        "## Sub-agent contract",
        "",
        "- This focus is delegated to a background sub-agent.",
        "- The sub-agent should not ask clarifying questions; make reasonable assumptions and proceed.",
        "- Mark subtasks completed in `docs/ssot/ssot.focus.current.yml` as you finish them.",
        "- Do not commit or push; the main session will review the diff and commit.",
        "- If a task requires destructive changes, stop and ask for confirmation.",
        "- Run py_compile / validation before finishing.",
    ]
    return prompt + "\n".join(notes)


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


def main():
    parser = argparse.ArgumentParser(description="Focus dispatcher for chaba")
    parser.add_argument("--inbox", help="Path to a specific inbox file to activate")
    parser.add_argument("--intake", help="Register a new request for focus intake")
    parser.add_argument("--park", action="store_true", help="Park the existing active focus in the same section before activating a new one")
    parser.add_argument("--sub-agent", action="store_true", help="Write a sub-agent contract in addition to NEXT_FOCUS.md")
    parser.add_argument("--dry-run", action="store_true", help="Show selection without modifying files")
    args = parser.parse_args()

    if args.intake:
        result, changed = handle_intake(args.intake, dry_run=args.dry_run)
        print(result["message"])
        if not args.dry_run and changed and os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit(changed, f"tweak: focus-dispatcher intake {args.intake[:50]}")
        sys.exit(0)

    changed = []
    if not args.dry_run:
        changed += archive_completed()

    validate_current()
    active_title, active_item = next_from_active(load_current())
    inbox = None
    if args.inbox:
        path = Path(args.inbox)
        inbox_doc = yaml.safe_load(path.read_text())
        inbox = inbox_doc.get("focus") or inbox_doc
        inbox["__file"] = path
    else:
        inbox = next_from_inbox()

    title = None
    item = None
    source = None
    changed_inbox = False

    if active_item and not args.inbox:
        title = active_title
        item = active_item
        source = None
        changed_inbox = False
        print(f"Active focus: {item['label']} ({title})")
    elif args.inbox and inbox:
        if not args.dry_run:
            title, item, target = activate_inbox(inbox, park=args.park)
            changed += [CURRENT, FOCUS, target]
        else:
            item = make_focus_item(
                inbox.get("label"),
                inbox.get("text", ""),
                inbox.get("branch"),
                inbox.get("priority", "medium"),
                inbox.get("tags", []),
                inbox.get("subtasks", []),
                source=str(inbox.get("__file")),
            )
            title = "Active Branch Focus" if inbox.get("branch") else "Active Shared Focus"
        source = str(inbox.get("__file"))
        changed_inbox = not args.dry_run
        print(f"Activated: {item['label']} ({title})")
    elif inbox:
        if not args.dry_run:
            title, item, target = activate_inbox(inbox, park=args.park)
            changed += [CURRENT, FOCUS, target]
        else:
            item = make_focus_item(
                inbox.get("label"),
                inbox.get("text", ""),
                inbox.get("branch"),
                inbox.get("priority", "medium"),
                inbox.get("tags", []),
                inbox.get("subtasks", []),
                source=str(inbox.get("__file")),
            )
            title = "Active Branch Focus" if inbox.get("branch") else "Active Shared Focus"
        source = str(inbox.get("__file"))
        changed_inbox = not args.dry_run
        print(f"Activated: {item['label']} ({title})")
    else:
        # No active or inbox; suggest a backlog item
        backlog = next_from_backlog()
        if backlog:
            prompt = generate_suggestion_prompt(backlog)
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            NEXT_FOCUS_MD.write_text(prompt)
            print(f"Suggested backlog: {backlog['label']}")
        else:
            print("No active or inbox focus found.")
            if NEXT_FOCUS_MD.exists():
                NEXT_FOCUS_MD.unlink()
        if not args.dry_run and changed and os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit(changed, "tweak: focus-dispatcher archived completed focuses")
        sys.exit(0)

    prompt = generate_prompt(title, item, source)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    NEXT_FOCUS_MD.write_text(prompt)
    print(f"Wrote {NEXT_FOCUS_MD}")

    if args.sub_agent:
        contract = generate_subagent_contract(title, item, source)
        SUBAGENT_CONTRACT_MD.write_text(contract)
        print(f"Wrote {SUBAGENT_CONTRACT_MD}")

    if not args.dry_run and changed and os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
        msg = f"tweak: focus-dispatcher activated {item['label']}"
        git_commit(changed, msg)


if __name__ == "__main__":
    main()
