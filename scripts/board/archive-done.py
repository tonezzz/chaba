#!/usr/bin/env python3
"""archive-done — daily retention sweep for verified done cards (KNB-1178).

Scans docs/ssot/kanban/cards/*.yml for cards that are column=done AND
action.verified AND updated older than ARCHIVE_DAYS (default 7), then
moves each through board-api POST /action {do: archive} — the write door
re-checks eligibility, writes the comms line, moves the file to
cards/archive/ (non-recursive glob keeps it off the board, in git) and
commits both sides of the move. This script never edits card files.

Card cap (Tony 2026-11-09): when the board still holds more than --cap
cards (default 600) after the verified pass, the oldest done cards older
than --days are archived too, verified or not ({do: archive, cap: true}),
until the board is back under the cap. Only column=done is ever touched,
cards with unanswered requests are skipped, and archive is reversible
(do=unarchive; files stay in git under cards/archive/).

Run on a host with repo access; default transport is the local board-api
(BOARD_API env, default http://127.0.0.1:8787 — idc03 served checkout).

Usage: archive-done.py [--apply] [--days N] [--cap N]
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


def scan(days: float) -> tuple[int, list[dict]]:
    """(total board cards, aged done cards oldest-first). Eligibility
    mirrors board-api do_archive so dry-run matches what the door accepts."""
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    total, out = 0, []
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if not isinstance(c, dict):
            continue
        total += 1
        if c.get("column") != "done":
            continue
        upd = str(c.get("updated") or "")
        try:
            when = dt.datetime.strptime(upd, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if when >= cutoff:
            continue
        open_req = any(not r.get("answer") for r in (c.get("requests") or [])
                       if isinstance(r, dict))
        out.append({"id": c.get("id") or p.stem, "file": p.name,
                    "updated": upd, "open_req": open_req,
                    "verified": bool((c.get("action") or {}).get("verified")),
                    "title": str(c.get("title") or "")[:70]})
    out.sort(key=lambda c: c["updated"])
    return total, out


def plan(days: float, cap: int) -> tuple[int, list[dict], list[dict]]:
    total, aged = scan(days)
    verified = [c for c in aged if c["verified"]]
    over = total - len(verified) - cap
    capped = [c for c in aged if not c["verified"] and not c["open_req"]]
    return total, verified, capped[:max(over, 0)]


def archive(cid: str, cap: bool) -> dict:
    body = {"id": cid, "do": "archive"}
    if cap:
        body["cap"] = True
    req = urllib.request.Request(
        API + "/action", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or "{}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually archive (default: dry-run)")
    ap.add_argument("--days", type=float, default=7.0,
                    help="age threshold (default 7)")
    ap.add_argument("--cap", type=int, default=600,
                    help="board card cap; 0 disables (default 600)")
    args = ap.parse_args()

    total, verified, capped = plan(args.days, args.cap or 10**9)
    print(f"board: {total} cards, cap {args.cap or 'off'}")
    print(f"{len(verified)} verified candidate(s) (done+verified, "
          f">{args.days}d)")
    print(f"{len(capped)} cap candidate(s) (oldest done, >{args.days}d, "
          f"no open requests)")
    for c in verified + capped:
        tag = "verified" if c["verified"] else "cap"
        print(f"  [{tag:<8}] {c['id']:<40} {c['updated']}  {c['title']}")
    left = total - len(verified) - len(capped)
    if args.cap and left > args.cap:
        print(f"note: {left} cards remain after sweep — still over cap "
              f"(not enough aged done cards)")
    if not args.apply:
        print("dry-run — pass --apply to archive")
        return 0

    ok = fail = 0
    for c in verified + capped:
        try:
            res = archive(c["id"], cap=not c["verified"])
            print(f"  archived {c['id']}: {res.get('message') or res}")
            ok += 1
        except Exception as e:
            print(f"  FAILED {c['id']}: {e}", file=sys.stderr)
            fail += 1
    print(f"done: {ok} archived, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
