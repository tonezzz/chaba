"""Thin CLI for focus dispatcher."""
import argparse
import os
import sys
from pathlib import Path

import yaml

from .actions import activate_inbox, handle_intake, make_focus_item
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
from .triage import next_from_active, next_from_backlog, next_from_inbox


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
