#!/usr/bin/env python3
"""card-run — launch an opencode session primed with a card context pack.

Pipeline: fetch card -> build context pack (card-context.py) -> write
pack file -> run `opencode run` (one-shot, non-interactive) in the
target repo dir -> optionally post the outcome as a card comment.

Default is --dry-run: prints the pack path and the command it would
exec, nothing touches the card or the repo.

Usage:
  card-run.py CARD_ID [--dir REPO] [--model M] [--ssh idc03]
  card-run.py ada-card-runner --dry-run     # default
  card-run.py ada-card-runner --dir ~/CascadeProjects/chaba --comment
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from importlib import import_module  # noqa: E402

_board_cli = import_module("board-cli")
_context = import_module("card-context")

WRAP = (
    "You are processing a kanban card end-to-end. Follow the pack's "
    "gates: worktree discipline, board-api for card mutations, "
    "git-safe-push + PR for repo changes, verify before claiming done. "
    "When finished, state clearly: what changed, how it was verified, "
    "and whether the done-condition holds.\n\n"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--dir", default=".",
                    help="working dir for the opencode session")
    ap.add_argument("--ssh", default="idc03")
    ap.add_argument("--api", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--comment", action="store_true",
                    help="post the run outcome as a card comment")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--execute", action="store_true",
                    help="actually run opencode (disables dry-run)")
    args = ap.parse_args()

    card = _context.fetch_card(args.id, args.ssh or None, args.api)
    pack = WRAP + _context.build(
        card, Path(args.dir).resolve(), max_files=8, head=40)

    pack_path = Path(tempfile.gettempdir()) / f"card-run-{args.id}.md"
    pack_path.write_text(pack)

    cmd = ["opencode", "run", "--archived",
           "--title", f"card {args.id}"]
    if args.model:
        cmd += ["-m", args.model]
    cmd += ["-f", str(pack_path),
            "Process this kanban card per the attached context pack."]

    if args.dry_run and not args.execute:
        print(f"pack: {pack_path} ({len(pack)} bytes)")
        print(f"cwd:  {Path(args.dir).resolve()}")
        print(f"cmd:  {' '.join(cmd)}")
        return 0

    r = subprocess.run(cmd, cwd=args.dir, capture_output=True,
                       text=True, timeout=1800)
    tail = (r.stdout or "")[-2000:]
    rc = r.returncode
    print(tail)
    if args.comment:
        body = (f"card-run opencode session (rc={rc}) on {args.dir}: "
                f"{tail[-400:]}")
        try:
            _board_cli.call(
                "POST", "/comment",
                {"id": args.id, "from": "card-run", "text": body},
                args.ssh or None)
        except Exception as exc:
            print(json.dumps({"comment_error": str(exc)[:200]}))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
