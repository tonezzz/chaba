#!/usr/bin/env python3
"""board-invariants — periodic checks that the board tells the truth.

Catches the wound classes that keep recurring (see ssot.repeat-asks.yml):

  R1  open Tony-facing request with <2 options — a buttonless ask
      (decision-buttons class; board-api guards new writes, this is the
      YAML-bypass + legacy-card catch)
  R2  request whose `suggested` is not among its options — the renderer
      can't mark the recommendation, Tony gets no ★
  R3  duplicate OPEN requests on one card — the merge-sweep dedup
      bypass class (differing request ids, same ask)
  V1  card in done/verified declaring `verify:` but no `[verify]`
      comm — guaranteed lifecycle bounce the next pass
  S1  action.status == running but the card's own trail went quiet
      >24h ago — stale claim; the runner report-back died
      (the 2026-10-15 parked-doing wave: 4 of these at once)
  S2  column=doing, no action block, last comm older than DOING_STALE_D
      — a parked card squatting in the active column
  Q1  action.status == queued but action.type != dispatch — kanban-
      dispatch can never claim it, so the card starves silently
      (queue-type-starvation-guard; 2026-10-13 zombie-sweep found 6
      queued for days with zero claims). Flagged after QUEUED_STARVE_H.

Read-only by design: prints findings; --alert writes one focus-inbox
file per violation class with findings (deduped by filename, so a
persistent violation doesn't spam). --strict exits 1 when findings
exist (CI gate use). No auto-fixes — the point is surfacing, not
guessing.

Usage: board-invariants.py [--alert] [--strict] [--card-dir DIR]
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARD_DIR = REPO / "docs/ssot/kanban/cards"
INBOX = REPO / "docs/ssot/focus-inbox"

DOING_STALE_D = 7
RUNNING_STALE_H = 24
QUEUED_STARVE_H = 24
# Mirrors lifecycle-check.py verify_gate: only `done` (not verified),
# only cards updated on/after the gate date, and ANY release-stage tag
# counts as evidence — not just [verify]. Keep these in sync.
VERIFY_GATE_AFTER = dt.datetime(2026, 10, 12)
VERIFY_EVIDENCE_RE = re.compile(
    r"\[\s*(verify|exp|alpha|beta|smoke|rc|prod)\s*\]", re.I)


def _ts(v):
    if isinstance(v, dt.datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(v)[:19], fmt)
        except ValueError:
            continue
    return None


def last_comm_at(card):
    ts = [_ts(m.get("at")) for m in (card.get("comms") or [])
          if isinstance(m, dict)]
    ts = [t for t in ts if t]
    return max(ts) if ts else None


def opt_labels(req):
    out = []
    for o in req.get("options") or []:
        out.append(o if isinstance(o, str) else str(o.get("id") or o.get("label") or ""))
    return [o for o in out if o]


def norm_ask(s):
    return re.sub(r"\W+", " ", str(s or "").lower()).strip()


def check_cards():
    now = dt.datetime.now()
    finds = {k: [] for k in ("R1", "R2", "R3", "V1", "S1", "S2", "Q1")}
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text()) or {}
        except Exception as e:
            finds["R1"].append(f"{p.name}: unreadable yaml ({e})")
            continue
        cid = c.get("id") or p.stem
        col = c.get("column")

        open_reqs = [r for r in (c.get("requests") or [])
                     if str(r.get("status") or "open") == "open"
                     and not r.get("answer")]
        asks = {}
        for r in open_reqs:
            opts = opt_labels(r)
            if len(opts) < 2:
                finds["R1"].append(
                    f"{cid}: open request {r.get('id')} has {len(opts)} option(s)")
            sug = r.get("suggested")
            if sug and str(sug) not in opts:
                finds["R2"].append(
                    f"{cid}: suggested '{sug}' not in options of {r.get('id')}")
            asks.setdefault(norm_ask(r.get("ask")), []).append(r.get("id"))
        for k, ids in asks.items():
            if k and len(ids) > 1:
                finds["R3"].append(f"{cid}: {len(ids)} dup open requests {ids}")

        if col == "done" and str(c.get("verify") or "").strip():
            upd = _ts(c.get("updated"))
            if upd and upd >= VERIFY_GATE_AFTER:
                texts = [str(m.get("text") or "") if isinstance(m, dict)
                         else str(m) for m in (c.get("comms") or [])]
                if not any(VERIFY_EVIDENCE_RE.search(t) for t in texts):
                    finds["V1"].append(
                        f"{cid}: done+verify:, no evidence-tagged comm "
                        "— lifecycle will bounce")

        act = c.get("action") or {}
        last = last_comm_at(c)
        if act.get("status") == "running" and last:
            age_h = (now - last).total_seconds() / 3600
            if age_h > RUNNING_STALE_H:
                finds["S1"].append(
                    f"{cid}: action running but trail quiet {age_h/24:.1f}d "
                    f"(runner {act.get('runner') or '?'})")
        if col == "doing" and not act and last:
            age_d = (now - last).days
            if age_d > DOING_STALE_D:
                finds["S2"].append(
                    f"{cid}: doing, no action, last comm {age_d}d ago")
        if act.get("status") == "queued" \
                and str(act.get("type") or "dispatch") != "dispatch":
            upd = _ts(c.get("updated"))
            age_h = ((now - upd).total_seconds() / 3600
                     if upd else QUEUED_STARVE_H + 1)
            if age_h > QUEUED_STARVE_H:
                finds["Q1"].append(
                    f"{cid}: queued {age_h/24:.1f}d but action.type="
                    f"{act.get('type')!r} — kanban-dispatch claims "
                    "type=dispatch only (starved)")
    return finds


def write_alerts(finds):
    """One inbox file per non-empty class — deduped by name so a
    persistent violation rewrites rather than stacks."""
    INBOX.mkdir(parents=True, exist_ok=True)
    names = {
        "R1": "buttonless-requests", "R2": "bad-suggested-option",
        "R3": "dup-open-requests", "V1": "done-missing-verify-evidence",
        "S1": "stale-running-claims", "S2": "parked-doing-claims",
        "Q1": "starved-queued-cards",
    }
    today = dt.date.today().isoformat()
    wrote = []
    for code, items in finds.items():
        if not items:
            continue
        slug = names[code]
        body = "\n".join(f"  - {i}" for i in items[:25])
        doc = {
            "title": f"board invariant violation: {slug} ({len(items)})",
            "subtitle": f"board-invariants.py {today}",
            "icon": "alert",
            "focus": {
                "label": f"Fix board invariants: {slug}",
                "text": f"{len(items)} violation(s) of class {code} — "
                        f"see ssot.repeat-asks.yml for the wound class.\n{body}",
                "branch": "chaba",
                "priority": "medium",
                "status": "draft",
                "tags": ["kanban", "invariants", code.lower()],
            },
            "ownership": {"owner": "tony", "locked": False, "lock_reason": ""},
            "source": {"date": today},
        }
        p = INBOX / f"invariant-{slug}.yml"
        p.write_text(yaml.safe_dump(doc, sort_keys=False, width=120))
        wrote.append(p.name)
    return wrote


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true",
                    help="write focus-inbox files per violation class")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when findings exist (CI gate)")
    ap.add_argument("--card-dir", type=Path, default=None)
    args = ap.parse_args()
    if args.card_dir:
        global CARD_DIR
        CARD_DIR = args.card_dir

    finds = check_cards()
    total = sum(len(v) for v in finds.values())
    for code, items in finds.items():
        mark = "FAIL" if items else "ok"
        print(f"[{mark}] {code}: {len(items)}")
        for i in items:
            print(f"      - {i}")
    if args.alert and total:
        for n in write_alerts(finds):
            print(f"alert -> {n}")
    print(f"board-invariants: {total} finding(s)")
    return 1 if (args.strict and total) else 0


if __name__ == "__main__":
    sys.exit(main())
