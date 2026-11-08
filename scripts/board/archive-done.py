#!/usr/bin/env python3
"""archive-done — daily retention sweep for verified done cards (KNB-1178).

Scans docs/ssot/kanban/cards/*.yml for cards that are column=done AND
action.verified AND updated older than ARCHIVE_DAYS (default 7), then
moves each through board-api POST /action {do: archive} — the write door
re-checks eligibility, writes the comms line, moves the file to
cards/archive/ (non-recursive glob keeps it off the board, in git) and
commits both sides of the move. This script never edits card files.

Run on a host with repo access; default transport is the local board-api
(BOARD_API env, default http://127.0.0.1:8787 — idc03 served checkout).

Usage: archive-done.py [--apply] [--days N]
  Default is dry-run: prints candidates, mutates nothing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARD_DIR = Path(os.environ.get(
    "KANBAN_CARD_DIR", REPO / "docs/ssot/kanban/cards"))
API = os.environ.get("BOARD_API", "http://127.0.0.1:8787")
TZ = dt.timezone(dt.timedelta(hours=7))  # board-api now() stamp


def candidates(days: float) -> list[dict]:
    """Card files eligible for archive — mirrors board-api do_archive so
    dry-run output matches what the door will accept."""
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    out = []
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if not isinstance(c, dict):
            continue
        if c.get("column") != "done":
            continue
        if not (c.get("action") or {}).get("verified"):
            continue
        upd = str(c.get("updated") or "")
        try:
            when = dt.datetime.strptime(upd, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if when < cutoff:
            out.append({"id": c.get("id") or p.stem,
                        "file": p.name, "updated": upd,
                        "title": str(c.get("title") or "")[:70]})
    return out


def archive(cid: str) -> dict:
    req = urllib.request.Request(
        API + "/action",
        data=json.dumps({"id": cid, "do": "archive"}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or "{}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually archive (default: dry-run)")
    ap.add_argument("--days", type=float, default=7.0,
                    help="age threshold (default 7)")
    args = ap.parse_args()

    cands = candidates(args.days)
    print(f"{len(cands)} archive candidate(s) "
          f"(done+verified, >{args.days}d):")
    for c in cands:
        print(f"  {c['id']:<40} {c['updated']}  {c['title']}")
    if not args.apply:
        print("dry-run — pass --apply to archive")
        return 0

    ok = fail = 0
    for c in cands:
        try:
            res = archive(c["id"])
            print(f"  archived {c['id']}: {res.get('message') or res}")
            ok += 1
        except Exception as e:
            print(f"  FAILED {c['id']}: {e}", file=sys.stderr)
            fail += 1
    print(f"done: {ok} archived, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
