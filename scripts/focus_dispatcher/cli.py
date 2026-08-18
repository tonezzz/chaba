"""Thin CLI for focus dispatcher."""
import argparse
import os
import sys
from pathlib import Path

import yaml

from .actions import activate_inbox, add_ready_safe, advance_focus, handle_intake, make_focus_item, next_focus
from .git import git_commit
from .history import archive_completed
from .prompts import (
    generate_prompt,
    generate_subagent_contract,
    generate_suggestion_prompt,
)
from .state import (
    CURRENT,
    FOCUS,
    NEXT_FOCUS_MD,
    REPORTS_DIR,
    SUBAGENT_CONTRACT_MD,
    load_current,
    validate_current,
)
from .triage import (
    dispatchable_backlog,
    next_from_active,
    next_from_backlog,
    next_from_inbox,
    safe_to_dispatch,
)


def main():
    parser = argparse.ArgumentParser(description="Focus dispatcher for chaba")
    parser.add_argument("--inbox", help="Path to a specific inbox file to activate")
    parser.add_argument("--intake", help="Register a new request for focus intake")
    parser.add_argument("--park", action="store_true", help="Park the existing active focus in the same section before activating a new one")
    parser.add_argument("--sub-agent", action="store_true", help="Write a sub-agent contract in addition to NEXT_FOCUS.md")
    parser.add_argument("--auto-dispatch", action="store_true", help="Scan backlog and write subagent contracts for eligible items without activating them")
    parser.add_argument("--safe-dispatch", action="store_true", help="Find the highest-scoring safe-to-parallel focus and add it to the Ready (Safe) section")
    parser.add_argument("--session", default="", help="Session ID to attach to a safe-dispatched focus for ownership/locking")
    parser.add_argument("--dry-run", action="store_true", help="Show selection without modifying files")
    parser.add_argument("--next", action="store_true", help="Activate the next highest-priority parked/deferred focus")
    parser.add_argument("--advance", action="store_true", help="Advance to the next focus only if the active one is complete")
    parser.add_argument("--resume-session", default=None, help="Restrict next/advance to a specific session name")
    args = parser.parse_args()

    if args.next:
        if args.dry_run:
            print("--next requires a real run")
            sys.exit(1)
        result = next_focus(resume_session=args.resume_session)
        print(result)
        if result.get("ok") and os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit([CURRENT, FOCUS], f"tweak: focus-dispatcher next {result.get('next', {}).get('label', '')[:50]}")
        sys.exit(0)

    if args.advance:
        if args.dry_run:
            print("--advance requires a real run")
            sys.exit(1)
        result = advance_focus(resume_session=args.resume_session)
        print(result)
        if result.get("ok") and os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit([CURRENT, FOCUS], f"tweak: focus-dispatcher advance {result.get('next', {}).get('label', '')[:50]}")
        sys.exit(0)

    if args.intake:
        result, changed = handle_intake(args.intake, dry_run=args.dry_run)
        print(result["message"])
        if not args.dry_run and changed and os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit(changed, f"tweak: focus-dispatcher intake {args.intake[:50]}")
        sys.exit(0)

    if args.auto_dispatch:
        eligible = dispatchable_backlog()
        if not eligible:
            print("No dispatchable backlog items found.")
            sys.exit(0)
        if not args.dry_run:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        for item in eligible:
            contract = generate_subagent_contract("Backlog - Triage Queue", item, None)
            path = REPORTS_DIR / f"SUBAGENT_CONTRACT_{item['label'].replace(' ', '_').replace('/', '_')[:40]}.md"
            if not args.dry_run:
                path.write_text(contract)
            print(f"{'Would write' if args.dry_run else 'Wrote'} {path}")
        sys.exit(0)

    if args.safe_dispatch:
        item = safe_to_dispatch()
        if not item:
            print("No safe-to-parallel focus found.")
            sys.exit(0)
        if args.dry_run:
            print(f"Would add to Ready (Safe): {item['label']} (source: {item.get('__source', 'unknown')})")
            sys.exit(0)
        new_item = add_ready_safe(item, session=args.session)
        print(f"Added to Ready (Safe): {new_item['label']}")
        if os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit([CURRENT], f"tweak: ready-safe dispatch {new_item['label'][:50]}")
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
