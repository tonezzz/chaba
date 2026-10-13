#!/usr/bin/env python3
"""review-digest.py — keep one standing card current with the review pile.

Tony asked (2026-10-11): a single summary card in the kanban that lists
what needs his review and links the related reports. This maintains
`review-digest` — its `note` field carries the live list, refreshed on a
timer. The card sits in `review` and is excluded from its own list.

Content:
  - every card in column=review (ref, title, age, report link if any)
  - cards with open requests aimed at tony (answers waiting)

Writes under the board-api flock so it can't race the API. The 60s
render sweep picks the change up; no service calls needed.
"""
from __future__ import annotations

import fcntl
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARD_DIR = REPO / "docs/ssot/kanban/cards"
LOCK = Path("/tmp/board-api.lock")
DIGEST_ID = "review-digest"


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) or {}


def main() -> int:
    review, asks = [], []
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            c = load(p)
        except Exception:
            continue
        cid = c.get("id") or p.stem
        if cid == DIGEST_ID:
            continue
        if c.get("column") == "review":
            ref = c.get("ref") or "----"
            rep = f" → {c['report']}" if c.get("report") else ""
            review.append(f"{ref} · {c.get('title') or cid}{rep}")
        open_reqs = [r for r in c.get("requests") or []
                     if isinstance(r, dict)
                     and r.get("status") not in ("answered", "closed", "done")
                     and r.get("to", "tony") == "tony"]
        if open_reqs and c.get("column") != "done":
            asks.append(cid)

    lines = [f"**{len(review)} in review:**"] if review else ["review pile empty"]
    lines += review[:15]
    if len(review) > 15:
        lines.append(f"… +{len(review)-15} more")
    if asks:
        lines.append(f"**{len(asks)} unanswered request(s):** "
                     + ", ".join(asks[:8]))
    note = "\n".join(lines)

    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        p = CARD_DIR / f"{DIGEST_ID}.yml"
        card = load(p) if p.exists() else {
            "id": DIGEST_ID,
            "title": "📋 Review digest — what needs Tony's eyes",
            "column": "review",
            "tags": ["kanban", "digest"],
        }
        if card.get("note") == note:
            return 0
        card["note"] = note
        card["column"] = "review"
        card["updated"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone(
                __import__("datetime").timedelta(hours=7))
        ).strftime("%Y-%m-%d %H:%M")
        p.write_text(yaml.safe_dump(card, allow_unicode=True,
                                    sort_keys=False, width=110))
    print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
