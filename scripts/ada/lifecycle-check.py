#!/usr/bin/env python3
"""lifecycle-check — release lifecycle gate enforcement for kanban cards.

Standard: docs/ssot/infrastructure/ssot.release-lifecycle.yml — the bars are
read from that file so threshold changes are config, not code.

A card opts into the lifecycle with a truthy `release:` field (convention:
the lane name, e.g. `release: tony`). Opted-in cards must carry the
stage-evidence comms tags the standard defines:

    [exp]    experiment/spike answered with evidence
    [alpha]  dev-twin scenarios green (2 consecutive) + lint/validate clean
    [beta]   real-use soak note (feedback/transcript extract; may cite
             ">= N sessions" to satisfy the sessions_min bar early)
    [smoke]  dev-twin browser smoke pass (dev-twin-smoke.py via playlived) —
             the required alpha -> pre-prod gate (Tony 2026-10-08)
    [rc]     pre-prod: parity diff + rollback plan (promote-lane.sh posts it)
    [prod]   production: deploy + post-deploy smoke result (promote-lane.sh)

Enforcement (mutating mode — runs inside kanban-sync.sh on the dedicated
kanban worktree; committing is the caller's job):

    column=review  missing [exp]/[alpha]            -> bounce to doing +
                   comms note naming the missing gate. Also stamps the
                   card's `soak_until` (first time seen in review +
                   bars.beta.soak_hours) — the soak timer lives on the card.
    column=done    missing any of [exp alpha beta smoke rc prod] OR the
                   beta soak bar unmet (soak_until not reached AND no
                   [beta] comms citing >= sessions_min sessions)
                                            -> bounce to doing + comms note.

Read-only gate mode (used by promote-lane.sh before --confirm):

    lifecycle-check.py --gate <card.yml> --stage review|preprod|done
        prints {"ok": bool, "missing": [...]} and exits 0/1/2.
        preprod = the s4 gate: exp+alpha+smoke tags + soak satisfied —
        no dev-twin playlive evidence, no promotion (standard gap 6).

Options:
    --cards-dir DIR   card directory (default <repo>/docs/ssot/kanban/cards)
    --standard FILE   standard yml (default ssot.release-lifecycle.yml)
    --now ISO         override "now" (testing)
    --dry-run         report actions without writing cards
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

REPO = Path(os.environ.get(
    "CHABA_REPO", str(Path(__file__).resolve().parents[2])))
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"
STANDARD = REPO / "docs" / "ssot" / "infrastructure" / "ssot.release-lifecycle.yml"

REVIEW_TAGS = ["exp", "alpha"]
DONE_TAGS = ["exp", "alpha", "beta", "smoke", "rc", "prod"]
PREPROD_TAGS = ["exp", "alpha", "smoke"]

TAG_RE = {t: re.compile(r"\[\s*%s\s*\]" % re.escape(t), re.I)
          for t in set(REVIEW_TAGS + DONE_TAGS)}
SESSIONS_RE = re.compile(r"(\d+)\s+(?:[\w-]+\s+){0,3}sessions?", re.I)
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def load_bars(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as e:
        print(f"lifecycle-check: cannot read standard {path}: {e}",
              file=sys.stderr)
        return {}
    return data.get("bars") or {}


def release_tracked(card: dict) -> bool:
    v = card.get("release")
    if v in (None, False):
        return False
    return str(v).strip().lower() not in ("", "none", "false", "no", "off")


def card_tags(card: dict) -> set:
    """The set of stage-evidence tags present anywhere in comms text."""
    tags = set()
    for c in card.get("comms") or []:
        text = str(c.get("text") or "") if isinstance(c, dict) else str(c)
        for tag, rx in TAG_RE.items():
            if rx.search(text):
                tags.add(tag)
    return tags


def parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 6], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def soak_satisfied(card: dict, bars: dict, now: datetime) -> tuple[bool, str]:
    """Beta soak bar: soak_until reached OR a [beta] comms citing >=
    sessions_min real sessions (standard: '72h soak OR >=3 sessions')."""
    until = parse_dt(card.get("soak_until"))
    if until is not None and now >= until:
        return True, f"soak_until {card['soak_until']} reached"
    need = int(bars.get("beta", {}).get("sessions_min") or 3)
    for c in card.get("comms") or []:
        text = str(c.get("text") or "") if isinstance(c, dict) else str(c)
        if not TAG_RE["beta"].search(text):
            continue
        m = SESSIONS_RE.search(text)
        if m and int(m.group(1)) >= need:
            return True, f"[beta] comms cites {m.group(1)} sessions"
    if until is None:
        return False, "soak_until unset (card never seen soaking in review)"
    return False, f"soak_until {card['soak_until']} not reached"


def missing_gates(card: dict, stage: str, bars: dict,
                  now: datetime) -> list:
    """The gate evidence a release card lacks for `stage`
    (review | preprod | done). Empty list = pass."""
    tags = card_tags(card)
    if stage == "review":
        need = REVIEW_TAGS
    elif stage == "preprod":
        need = PREPROD_TAGS
    else:
        need = DONE_TAGS
    missing = [f"[{t}]" for t in need if t not in tags]
    if stage in ("preprod", "done"):
        ok, why = soak_satisfied(card, bars, now)
        if not ok:
            hours = int(bars.get("beta", {}).get("soak_hours") or 72)
            missing.append(f"beta soak ({why}; bar {hours}h or "
                           f">={bars.get('beta', {}).get('sessions_min', 3)} "
                           "sessions)")
    return missing


def comms_add(card: dict, frm: str, text: str, now: datetime) -> None:
    card.setdefault("comms", []).append(
        {"at": now.strftime("%Y-%m-%d %H:%M"), "from": frm, "text": text})


def stamp_soak(card: dict, bars: dict, now: datetime) -> bool:
    """Set soak_until the first time a release card is seen in review —
    that is the s3 soak clock. Returns True when it stamped."""
    if card.get("soak_until"):
        return False
    hours = int(bars.get("beta", {}).get("soak_hours") or 72)
    until = now + timedelta(hours=hours)
    card["soak_until"] = until.strftime("%Y-%m-%d %H:%M")
    comms_add(card, "chaba",
              f"[lifecycle] beta soak clock started — soak_until "
              f"{card['soak_until']} (bar {hours}h or "
              f">={bars.get('beta', {}).get('sessions_min', 3)} sessions)",
              now)
    return True


def gate(card: dict, stage: str, bars: dict, now: datetime) -> dict:
    return {"id": card.get("id"), "stage": stage,
            "release": card.get("release"),
            "ok": not missing_gates(card, stage, bars, now),
            "missing": missing_gates(card, stage, bars, now)}


def enforce_card(path: Path, bars: dict, now: datetime,
                 dry: bool) -> list:
    """One card. Returns a list of action lines taken (or would take)."""
    try:
        card = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return []
    if not isinstance(card, dict) or not release_tracked(card):
        return []
    col = card.get("column")
    actions = []

    if col == "review":
        if stamp_soak(card, bars, now):
            actions.append(f"{card.get('id')}: soak_until -> "
                           f"{card['soak_until']}")
        missing = missing_gates(card, "review", bars, now)
        if missing:
            card["column"] = "doing"
            card["updated"] = now.strftime("%Y-%m-%d %H:%M")
            comms_add(
                card, "chaba",
                f"[lifecycle] bounced review->doing — missing stage "
                f"evidence: {', '.join(missing)}. Append tagged comms "
                "([exp]/[alpha]/[beta]/[smoke]/[rc]/[prod]) per "
                "ssot.release-lifecycle.yml, then move back.", now)
            actions.append(f"{card.get('id')}: bounced review->doing "
                           f"(missing {', '.join(missing)})")
    elif col == "done":
        missing = missing_gates(card, "done", bars, now)
        if missing:
            card["column"] = "doing"
            card["updated"] = now.strftime("%Y-%m-%d %H:%M")
            comms_add(
                card, "chaba",
                f"[lifecycle] bounced done->doing — release card missing "
                f"evidence: {', '.join(missing)}. Append the tagged comms "
                "or satisfy the soak bar, then re-close.", now)
            actions.append(f"{card.get('id')}: bounced done->doing "
                           f"(missing {', '.join(missing)})")

    if actions and not dry:
        path.write_text(yaml.safe_dump(card, sort_keys=False,
                                       allow_unicode=True, width=110))
    return actions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards-dir", type=Path, default=CARDS)
    ap.add_argument("--standard", type=Path, default=STANDARD)
    ap.add_argument("--now", help="ISO datetime override (testing)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--gate", type=Path, metavar="CARD.yml",
                    help="read-only gate check on one card file")
    ap.add_argument("--stage", choices=["review", "preprod", "done"],
                    default="done")
    args = ap.parse_args()

    now = parse_dt(args.now) if args.now else datetime.now()
    if now is None:
        sys.exit(f"lifecycle-check: bad --now {args.now!r}")
    bars = load_bars(args.standard)

    if args.gate:
        try:
            card = yaml.safe_load(args.gate.read_text()) or {}
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 2
        if not release_tracked(card):
            print(json.dumps({"ok": True, "release": None,
                              "note": "card not release-tracked — "
                                      "no lifecycle gates"}))
            return 0
        out = gate(card, args.stage, bars, now)
        print(json.dumps(out))
        return 0 if out["ok"] else 1

    actions = []
    for path in sorted(args.cards_dir.glob("*.yml")):
        actions.extend(enforce_card(path, bars, now, args.dry_run))
    tag = "DRY " if args.dry_run else ""
    if actions:
        for a in actions:
            print(f"lifecycle-check: {tag}{a}")
    else:
        print("lifecycle-check: all release cards gate-clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
