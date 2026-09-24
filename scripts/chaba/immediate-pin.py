#!/usr/bin/env python3
"""immediate-pin.py — upsert one entry in ~/.local/share/chaba/immediate.yml.

Entries are keyed by session id: the session-end hook writes deterministic
fields; a session may call this mid-flight to pin task/next/open itself.
Rendered into context by render-memory.py source kind `immediate`.
"""
import argparse
import os
import pathlib
import subprocess
import sys
import time

import yaml

STORE = pathlib.Path("~/.local/share/chaba/immediate.yml").expanduser()
KEEP = 10  # hard cap on stored entries (newest first)


def git(*args):
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=os.environ.get("DEVIN_SESSION_ID", "unknown"))
    ap.add_argument("--task")
    ap.add_argument("--next", dest="next_step")
    ap.add_argument("--open", dest="open_items", action="append", default=[])
    ap.add_argument("--pointer")
    ap.add_argument("--ttl-hours", type=int, default=72)
    args = ap.parse_args()

    doc = {"entries": []}
    if STORE.exists():
        try:
            doc = yaml.safe_load(STORE.read_text()) or {"entries": []}
        except Exception:
            pass
    entries = [e for e in doc.get("entries", []) if isinstance(e, dict)]

    entry = next((e for e in entries if e.get("session") == args.session), None)
    if entry is None:
        entry = {"session": args.session}
        entries.append(entry)
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    entry["ttl_hours"] = args.ttl_hours
    for key, val in (("task", args.task), ("next", args.next_step), ("pointer", args.pointer)):
        if val:
            entry[key] = val
    if args.open_items:
        entry["open"] = args.open_items
    if "branch" not in entry:
        entry["branch"] = git("rev-parse", "--abbrev-ref", "HEAD") or None
    if "last_commit" not in entry:
        entry["last_commit"] = git("log", "-1", "--format=%h %s") or None
    if "pointer" not in entry:
        p = pathlib.Path(
            f"~/.local/share/devin/cli/summaries/history_{args.session}.md"
        ).expanduser()
        if p.exists():
            entry["pointer"] = str(p)

    entries.sort(key=lambda e: str(e.get("ts", "")), reverse=True)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(yaml.safe_dump({"entries": entries[:KEEP]}, allow_unicode=True, sort_keys=False))
    print(f"pinned: {args.session} ({len(entries[:KEEP])} entries)")


if __name__ == "__main__":
    sys.exit(main())
