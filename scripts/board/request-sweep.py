#!/usr/bin/env python3
"""request-sweep — one escalation ping for board requests rotting >12h.

Runs inside the kanban-sync tick (every 15min on tony-dell). Scans all
cards for requests that target tony, are still open, and have waited
longer than BOARD_SWEEP_AGE_H (default 12): sends ONE batched push via
board_notify.py and stamps `escalated_at` on each request so it fires
exactly once — quiet-by-design, no re-pings, no per-request spam.

Card writes hold /tmp/board-api.lock — the single-writer rule for card
YAML applies to this script too. If the push fails, nothing is stamped
and the next tick retries (a down channel produces no visible spam).

Request age comes from `at` (stamped by board-api since kanban-push-
notify); for older requests it falls back to the card comms 'raised
request <id>' timestamp, then the card's `updated` stamp.

Usage: request-sweep.py [--dry-run]
Env:   BOARD_SWEEP_AGE_H (default 12), CHABA_REPO (cards checkout),
       BOARD_NOTIFY_* (channel — see board_notify.py).
"""

from __future__ import annotations

import fcntl
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_notify as bn

REPO = Path(os.environ.get(
    "CHABA_REPO", str(Path(__file__).resolve().parents[2])))
CARD_DIR = REPO / "docs" / "ssot" / "kanban" / "cards"
LOCK = Path("/tmp/board-api.lock")
AGE_H = float(os.environ.get("BOARD_SWEEP_AGE_H", "12"))
TZ = timezone(timedelta(hours=7))  # same stamp board-api's now() writes


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def parse_ts(raw) -> datetime | None:
    """'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD' -> naive datetime, else None."""
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 2], fmt)
        except ValueError:
            continue
    return None


def request_age(req: dict, card: dict, ref: datetime) -> float | None:
    """Hours the request has been open, or None if undatable."""
    ts = parse_ts(req.get("at"))
    if ts is None:
        rid = req.get("id")
        for m in card.get("comms") or []:
            if rid and f"raised request {rid}" in str(m.get("text")):
                ts = parse_ts(m.get("at"))
                if ts:
                    break
    if ts is None:
        ts = parse_ts(card.get("updated"))
    if ts is None:
        return None
    return (ref - ts).total_seconds() / 3600


def overdue_requests(card: dict, ref: datetime) -> list[tuple[dict, float]]:
    """[(req, age_h)] for open, tony-targeted, un-escalated, >AGE_H."""
    if card.get("column") == "done":
        return []
    out = []
    for r in card.get("requests") or []:
        if not isinstance(r, dict):
            continue
        if r.get("status") == "answered" or r.get("escalated_at"):
            continue
        if r.get("to", "tony") != "tony" or r.get("from") == "tony":
            continue
        age = request_age(r, card, ref)
        if age is not None and age >= AGE_H:
            out.append((r, age))
    return out


def main() -> int:
    dry = "--dry-run" in sys.argv
    ref = now()
    # pass 1 (unlocked): find candidates; re-verified under the lock
    candidates = []
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            card = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        hits = overdue_requests(card, ref)
        if hits:
            candidates.append((p, card.get("id") or p.stem, hits))

    if not candidates:
        print(f"request-sweep: no open requests >{AGE_H:g}h")
        return 0

    if dry:
        for _, cid, hits in candidates:
            for r, age in hits:
                print(f"  would escalate {cid}/{r.get('id')} ({age:.0f}h)")
        print(f"request-sweep: dry-run — {sum(len(h) for _, _, h in candidates)}"
              f" overdue across {len(candidates)} card(s)")
        return 0

    # pass 2 (locked): re-verify fresh state, push, then stamp
    stamped = 0
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        lines = []
        touched = []  # (path, card, [req_ids])
        for p, cid, _ in candidates:
            try:
                card = yaml.safe_load(p.read_text()) or {}
            except Exception:
                continue
            hits = overdue_requests(card, ref)
            if not hits:
                continue  # answered/escalated since pass 1
            for r, age in hits:
                lines.append(
                    f"• {cid}: {str(r.get('ask'))[:80]} ({age:.0f}h)")
            touched.append((p, card, [r.get("id") for r, _ in hits]))
        if not touched:
            print("request-sweep: overdue requests resolved before lock")
            return 0
        n = sum(len(ids) for _, _, ids in touched)
        if n == 1:
            p, card, ids = touched[0]
            req = next(r for r in card["requests"] if r.get("id") == ids[0])
            ok = bn.send(
                f"Board request unanswered >{AGE_H:g}h",
                f"{card.get('id') or p.stem}: {str(req.get('ask'))[:180]}")
        else:
            ok = bn.send(f"Board: {n} requests waiting >{AGE_H:g}h",
                         "\n".join(lines[:10])
                         + (f"\n… +{n - 10} more" if n > 10 else ""))
        if not ok:
            print("request-sweep: push failed — nothing stamped, "
                  "retrying next tick")
            return 1
        stamp = ref.strftime("%Y-%m-%d %H:%M")
        for p, card, ids in touched:
            for r in card.get("requests") or []:
                if r.get("id") in ids:
                    r["escalated_at"] = stamp
                    stamped += 1
            card.setdefault("comms", []).append({
                "at": stamp, "from": "chaba",
                "text": f"request-sweep: {len(ids)} request(s) unanswered "
                        f">{AGE_H:g}h — escalation pushed"})
            card["updated"] = stamp
            p.write_text(yaml.safe_dump(card, allow_unicode=True,
                                        sort_keys=False, width=110))
    print(f"request-sweep: escalated {stamped} request(s) across "
          f"{len(touched)} card(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
