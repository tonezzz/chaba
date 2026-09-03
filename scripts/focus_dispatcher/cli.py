"""Thin CLI for focus dispatcher."""
import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from .actions import (
    activate_inbox,
    add_ready_safe,
    advance_focus,
    handle_intake,
    make_focus_item,
    next_focus,
    process_ready_safe,
)
from .git import git_commit
from .history import archive_completed
from .prompts import (
    generate_prompt,
    generate_subagent_contract,
    generate_suggestion_prompt,
)
from .state import (
    ACTIVE,
    BACKLOG,

    FOCUS,
    NEXT_FOCUS_MD,
    REPORTS_DIR,
    SUBAGENT_CONTRACT_MD,
    load_active,
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
    parser.add_argument("--process-ready", action="store_true", help="Pick the next unlocked Ready (Safe) item and write a SUBAGENT_CONTRACT for remote execution")
    parser.add_argument("--auto-process", action="store_true", help="Find the highest safe-to-parallel focus, promote it to Ready (Safe), and write a SUBAGENT_CONTRACT for tony-dell")
    parser.add_argument("--host", default="tony_dell", help="Target host for --process-ready and --auto-process (default: tony_dell)")
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
            git_commit([ACTIVE, FOCUS], f"tweak: focus-dispatcher next {result.get('next', {}).get('label', '')[:50]}")
        sys.exit(0)

    if args.advance:
        if args.dry_run:
            print("--advance requires a real run")
            sys.exit(1)
        result = advance_focus(resume_session=args.resume_session)
        print(result)
        if result.get("ok") and os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit([ACTIVE, FOCUS], f"tweak: focus-dispatcher advance {result.get('next', {}).get('label', '')[:50]}")
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
        item = safe_to_dispatch(session=args.session)
        if not item:
            print("No safe-to-parallel focus found.")
            sys.exit(0)
        if args.dry_run:
            print(f"Would add to Ready (Safe): {item['label']} (source: {item.get('__source', 'unknown')})")
            sys.exit(0)
        new_item = add_ready_safe(item, session=args.session)
        print(f"Added to Ready (Safe): {new_item['label']}")
        if os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit([BACKLOG], f"tweak: ready-safe dispatch {new_item['label'][:50]}")
        sys.exit(0)

    if args.process_ready:
        result = process_ready_safe(host=args.host, session=args.session, dry_run=args.dry_run)
        if not result:
            print("No Ready (Safe) item found.")
            sys.exit(0)
        if args.dry_run:
            print(f"Would process on {result['host']}: {result['label']} -> {result['path']}")
            sys.exit(0)
        print(f"Dispatched to {result['host']}: {result['label']}")
        print(f"Contract: {result['path']}")
        print("To invoke the subagent:")
        print(json.dumps({
            "tool": "run_subagent",
            "title": f"Ready (Safe) — {result['label']}",
            "profile": result['item'].get('subagent', {}).get('profile', 'subagent_general'),
            "task": f"Read and execute the subagent contract at {result['path']}. Work on host `{result['host']}` using mcp_debug with `host: {result['host']}`. Update the Ready (Safe) item subtask status in docs/ssot/ssot.focus.current.backlog.yml when done. Do not commit; the main session will review.",
            "is_background": True,
        }, indent=2))
        if os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit([BACKLOG], f"tweak: process-ready {result['label'][:50]}")
        sys.exit(0)

    if args.auto_process:
        result = process_ready_safe(host=args.host, session=args.session, dry_run=args.dry_run)
        if not result:
            candidate = safe_to_dispatch(session=args.session)
            if not candidate:
                print("No safe-to-parallel focus found.")
                sys.exit(0)
            if args.dry_run:
                print(f"Would auto-process on {args.host}: {candidate['label']} -> {args.host}")
                sys.exit(0)
            new_item = add_ready_safe(candidate, session=args.session)
            result = process_ready_safe(host=args.host, session=args.session, dry_run=args.dry_run)
        if not result:
            print("No Ready (Safe) item to process.")
            sys.exit(0)
        print(f"Auto-processed to {result['host']}: {result['label']}")
        print(f"Contract: {result['path']}")
        print("To invoke the subagent:")
        print(json.dumps({
            "tool": "run_subagent",
            "title": f"Ready (Safe) — {result['label']}",
            "profile": result['item'].get('subagent', {}).get('profile', 'subagent_general'),
            "task": f"Read and execute the subagent contract at {result['path']}. Work on host `{result['host']}` using mcp_debug with `host: {result['host']}`. Update the Ready (Safe) item subtask status in docs/ssot/ssot.focus.current.backlog.yml when done. Do not commit; the main session will review.",
            "is_background": True,
        }, indent=2))
        if os.environ.get("FOCUS_DISPATCHER_COMMIT") == "1":
            git_commit([BACKLOG], f"tweak: auto-process {result['label'][:50]}")
        sys.exit(0)

    changed = []
    if not args.dry_run:
        changed += archive_completed()

    validate_current()
    active_title, active_item = next_from_active(load_active())
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
            changed += [ACTIVE, FOCUS, target]
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
            changed += [ACTIVE, FOCUS, target]
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
