#!/usr/bin/env python3
"""lab-review-sweep — keeps the Lab lane honest (weekly).

Scans docs/ssot/kanban/cards/*.yml for column==lab and flags any card
where lab.review_by is past due and lab.outcome is unset. For each
flagged card it:

  * appends a comms entry (from: chaba) — "lab review due — promote,
    retire, or extend?"
  * appends a requests: entry (id: lab-review) with one-click options
    [promote→backlog, retire→done, extend 2w] — unless an open
    lab-review request already exists (idempotent; repeats weekly).

It does NOT decide — the human/actor picks an option on the card. When a
lab-review request comes back answered, the next sweep executes it:

  promote → column=backlog, lab.outcome=promote
  retire  → column=done,    lab.outcome=retire
  extend  → lab.review_by += 14d, outcome cleared (fresh decision then)

Run by chaba-lab-sweep.timer on tony-dell.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"
TODAY = datetime.date.today().isoformat()

OPTIONS = [
    {"id": "promote", "label": "promote → backlog — it earned a real card"},
    {"id": "retire", "label": "retire → done — write the learning in comms first"},
    {"id": "extend", "label": "extend 2w — set a new lab.review_by (+14d)"},
]


def execute_decision(card: dict, req: dict) -> bool:
    """Apply an answered lab-review request. Returns True if the card
    changed."""
    answer = (req.get("answer") or "").strip().lower()
    lab = card.setdefault("lab", {})
    today = datetime.date.today()
    if answer.startswith("promote"):
        card["column"] = "backlog"
        lab["outcome"] = "promote"
    elif answer.startswith("retire"):
        card["column"] = "done"
        lab["outcome"] = "retire"
    elif answer.startswith("extend"):
        review_by = datetime.date.fromisoformat(str(lab["review_by"]))
        lab["review_by"] = (review_by + datetime.timedelta(days=14)).isoformat()
        lab.pop("outcome", None)
    else:
        return False
    card.setdefault("comms", []).append({
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "from": "chaba",
        "text": f"lab decision executed: {answer}",
    })
    return True


def main() -> int:
    flagged, executed = [], []
    for path in sorted(CARDS.glob("*.yml")):
        try:
            card = yaml.safe_load(path.read_text()) or {}
        except Exception:
            continue
        if card.get("column") != "lab":
            continue
        lab = card.get("lab") or {}
        review_by = lab.get("review_by")

        # Phase 1 — execute answered lab-review decisions (any card that
        # still sits in lab; promote/retire moves it out, extend re-dates).
        decided = False
        for req in card.get("requests") or []:
            if (req.get("id") == "lab-review"
                    and req.get("status") == "answered"
                    and not req.get("executed")):
                if execute_decision(card, req):
                    req["executed"] = TODAY
                    decided = True
                else:
                    req["executed"] = f"unrecognized: {req.get('answer')}"
        if decided:
            path.write_text(yaml.safe_dump(
                card, sort_keys=False, allow_unicode=True))
            executed.append(card.get("id") or path.stem)
            if card.get("column") != "lab":
                continue
            review_by = lab.get("review_by")

        # Phase 2 — flag overdue lab cards with no outcome.
        if not review_by or lab.get("outcome"):
            continue
        if str(review_by) >= TODAY:
            continue

        changed = False
        reqs = card.setdefault("requests", [])
        if not any(r.get("id") == "lab-review" and r.get("status") == "open"
                   for r in reqs):
            reqs.append({
                "id": "lab-review",
                "ask": (f"Lab review_by {review_by} has passed with no "
                        "outcome — promote, retire, or extend?"),
                "status": "open",
                "options": OPTIONS,
            })
            changed = True
        comms = card.setdefault("comms", [])
        nudge = "lab review due — promote, retire, or extend?"
        if not any(nudge in (m.get("text") or "") for m in comms[-5:]):
            comms.append({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "from": "chaba",
                "text": nudge,
            })
            changed = True
        if changed:
            path.write_text(yaml.safe_dump(
                card, sort_keys=False, allow_unicode=True))
        flagged.append(card.get("id") or path.stem)

    out = []
    if flagged:
        out.append(f"{len(flagged)} overdue: {', '.join(flagged)}")
    if executed:
        out.append(f"{len(executed)} decisions executed: "
                   f"{', '.join(executed)}")
    print("lab-review-sweep: " + ("; ".join(out) if out else "all clear"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
