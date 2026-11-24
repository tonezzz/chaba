#!/usr/bin/env python3
"""handoff-packet.py -- Session Handoff Packet scaffold + field validator.

Canonical spec: docs/ssot/ssot.knowledge-capture.yml#Session Handoff Packet (required).

Commands:
    scaffold   Print a prefilled markdown scaffold (as_of auto-filled) to stdout,
               or to --out FILE. Agent fills the <placeholders>; nothing here
               writes to a durable sink.
    validate   Check a packet file contains every required field line; exit 1
               with the missing fields listed.

This is deliberately scaffold-only: saving to OpenChamber knowledge or card
comms stays with the agent (auth/path handling is sink-specific). See
.opencode/commands/handoff-packet.md for the save paths.

Usage:
    handoff-packet.py scaffold [--objective TEXT] [--state done|in progress|blocked]
                               [--refs TEXT] [--out FILE]
    handoff-packet.py validate PACKET.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

REQUIRED = [
    "objective",
    "as_of",
    "current_state",
    "canonical_refs",
    "open_asks_decisions",
    "next_action",
    "where_filed",
    "notes",
]

TEMPLATE = """\
# Session handoff — {objective} ({as_of})
- objective: {objective}
- as_of: {as_of}
- current_state: {state} — <evidence refs>
- canonical_refs: {refs}
- open_asks_decisions: <none | ask/decision -> owner/options/default + durable sink/ID>
- next_action: <single concrete next step>
- where_filed: <item -> sink/ID/path> (mandatory; include "none" only if truly nothing captured)
- notes: <risks/gaps/refresh queries if any; label canonical(served)/branch/unmerged/live runtime when relevant>
"""


def now_as_of() -> str:
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")


def scaffold(args) -> int:
    as_of = now_as_of()
    objective = args.objective or "<objective>"
    state = args.state or "<done | in progress | blocked>"
    refs = args.refs or "<SSOT keys/paths, card IDs, lesson/report/artifact IDs, commits/paths>"
    text = TEMPLATE.format(objective=objective, as_of=as_of, state=state, refs=refs)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out} (as_of={as_of})")
    else:
        sys.stdout.write(text)
    return 0


def validate(args) -> int:
    path = Path(args.packet)
    if not path.is_file():
        sys.stderr.write(f"handoff-packet: no such file: {path}\n")
        return 2
    text = path.read_text()
    missing = [f for f in REQUIRED if not re.search(rf"(?m)^-\s*{re.escape(f)}\s*:", text)]
    # where_filed must be explicit: reject an empty value or bare placeholder.
    m = re.search(r"(?m)^-\s*where_filed\s*:\s*(.*)$", text)
    wf_ok = bool(m) and m.group(1).strip() not in ("", "<item -> sink/ID/path>") \
        and "<item ->" not in m.group(1)
    if m and not wf_ok:
        missing.append("where_filed (explicit value required)")
    if missing:
        sys.stderr.write("handoff-packet: missing/invalid fields:\n")
        for f in missing:
            sys.stderr.write(f"  - {f}\n")
        return 1
    print(f"handoff-packet: OK ({path})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scaffold", help="print a prefilled packet scaffold")
    sc.add_argument("--objective", help="prefill objective (default: placeholder)")
    sc.add_argument("--state", choices=["done", "in progress", "blocked"],
                    help="prefill current_state")
    sc.add_argument("--refs", help="prefill canonical_refs")
    sc.add_argument("--out", help="write scaffold to FILE instead of stdout")
    sc.set_defaults(fn=scaffold)

    va = sub.add_parser("validate", help="check required fields in a packet file")
    va.add_argument("packet")
    va.set_defaults(fn=validate)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
