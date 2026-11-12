#!/usr/bin/env python3
"""card-pick — select the next kanban card to process by strategy.

Read-only: only GETs /cards. Strategies:

  sweep      — stalest actionable card (doing first, then backlog),
               ordered by oldest `updated`
  high-value — priority high>medium>low, ties by oldest `updated`
  stale      — doing cards idle >= --days (default 7)
  queue      — cards with action.status == queued (dispatch rail order)

A card is actionable when it is not waiting on a human:
no requests[] with status not in (answered, closed), and no
action.status in (claimed, running) — those already have an owner.

Usage:
  card-pick.py STRATEGY [--days N] [--limit N] [--json]
  card-pick.py sweep --ssh idc03
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from importlib import import_module  # noqa: E402

_board_cli = import_module("board-cli")


def fetch_cards(ssh: str | None, api: str | None) -> list[dict]:
    if api:
        _board_cli.API = api
    out = _board_cli.call("GET", "/cards?limit=500", None, ssh)
    return out.get("cards") or []


def parse_ts(card: dict) -> datetime:
    raw = str(card.get("updated") or card.get("created") or "")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:16], fmt).replace(
                tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def is_actionable(card: dict) -> tuple[bool, str]:
    """A card the runner may pick: not finished, not waiting, not owned."""
    if card.get("column") in ("done", "archive"):
        return False, "finished"
    for r in card.get("requests") or []:
        if r.get("status") not in ("answered", "closed"):
            return False, f"open request {r.get('id', '?')}"
    action = card.get("action") or {}
    if action.get("status") in ("claimed", "running"):
        return False, f"action {action.get('status')}"
    return True, "ok"


PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


def pick(cards: list[dict], strategy: str, days: int,
         now: datetime) -> list[tuple[dict, str]]:
    """Return [(card, why)] best-first."""
    scored = []
    for c in cards:
        ok, reason = is_actionable(c)
        if not ok:
            continue
        age = (now - parse_ts(c)).days
        col = c.get("column") or "backlog"
        if strategy == "queue":
            action = c.get("action") or {}
            if action.get("status") == "queued":
                scored.append((c, "queued for dispatch"))
            continue
        if strategy == "stale":
            if col == "doing" and age >= days:
                scored.append((c, f"doing, idle {age}d"))
            continue
        if strategy == "sweep":
            weight = 1 if col == "doing" else 0
            scored.append((c, f"{col}, untouched {age}d", (weight, age)))
            continue
        if strategy == "high-value":
            rank = PRIORITY_RANK.get(str(c.get("priority") or ""), 0)
            if rank:
                scored.append(
                    (c, f"priority {c['priority']}, untouched {age}d",
                     (rank, age)))
            continue
    if strategy in ("sweep", "high-value"):
        scored.sort(key=lambda t: t[2], reverse=True)
        return [(c, w) for c, w, _ in scored]
    if strategy == "stale":
        scored.sort(key=lambda t: parse_ts(t[0]))
        return scored
    return scored  # queue: board order preserved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy",
                    choices=["sweep", "high-value", "stale", "queue"])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--ssh", default="idc03",
                    help="host board-api runs on ('' = local BOARD_API)")
    ap.add_argument("--api", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ssh = args.ssh or None
    try:
        cards = fetch_cards(ssh, args.api)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:300]}))
        return 2

    hits = pick(cards, args.strategy, args.days,
                datetime.now(timezone.utc))
    out = {
        "ok": True,
        "strategy": args.strategy,
        "picks": [
            {
                "id": c.get("id"),
                "ref": c.get("ref"),
                "title": c.get("title"),
                "column": c.get("column"),
                "priority": c.get("priority"),
                "why": why,
            }
            for c, why in hits[: args.limit]
        ],
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for p in out["picks"]:
            print(f"{p['ref'] or p['id']:>10}  [{p['column']}] "
                  f"{p['title']}  — {p['why']}")
        if not out["picks"]:
            print(f"no actionable {args.strategy} cards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
