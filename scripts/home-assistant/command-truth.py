#!/usr/bin/env python3
"""command-truth — every state change on a watched HA entity must have a
named, allowlisted commander. Unattributed changes = drift = card.

The 2026-10-12 TONY-TV symptom: the TV woke ~03:20 local every night and a
cast session attached — logbook showed the wake but nothing admitted
commanding it. Detection existed (vcast flap metrics, audit-cast runaway
guard) but nothing reconciled "who commanded this". This is that reconcile.

Per watched entity (config: docs/ssot/infrastructure/ssot.command-truth.yml):

    history rows in the window -> context attribution:
        context.user_id   -> an HA user/service-account (attributable)
        context.parent_id -> an automation/script run (attributable)
        no context        -> device-side / integration poll / LAN chatter
                           (unattributed — the interesting class)

    allowed_commanders (per entity): user_ids, automation/script entity_ids,
    and 'unattributed-ok' for entities where integration noise is normal.
    quiet_hours (per entity): local HH:MM-HH:MM — inside the window ANY
    change that isn't attributed to an allowed commander is a violation.

Output: deltas -> kanban card `cast-auto-command-truth` (same lifecycle as
runner-fleet-health / audit-hosts cards). Runs in the chaba-system-report
chain on tony-dell (--cards only there).

    python3 command-truth.py            # deltas to stdout
    python3 command-truth.py --cards    # + card upsert (served checkout)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SSOT = REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.command-truth.yml"
CARDS_DIR = Path(os.environ.get(
    "CHABA_AUDIT_CARDS_DIR",
    str(REPO_ROOT / "docs" / "ssot" / "kanban" / "cards")))
CARD_ID = "cast-auto-command-truth"


def ha_get(base: str, token: str, path: str):
    req = urllib.request.Request(
        base + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _in_quiet(ts: datetime, quiet: str) -> bool:
    """quiet: 'HH:MM-HH:MM' local; may wrap midnight."""
    try:
        a, b = quiet.split("-")
        sh, sm = (int(x) for x in a.split(":"))
        eh, em = (int(x) for x in b.split(":"))
        t = ts.hour * 60 + ts.minute
        lo, hi = sh * 60 + sm, eh * 60 + em
        return t >= lo or t < hi if lo > hi else lo <= t < hi
    except Exception:
        return False


def audit(base: str, token: str, cfg: dict, hours: int) -> list[str]:
    deltas = []
    end = datetime.now().astimezone()
    start = end - timedelta(hours=hours)
    for ent in cfg.get("entities", []):
        eid = ent["entity_id"]
        allowed_users = set(ent.get("allowed_users", []))
        allowed_callers = set(ent.get("allowed_callers", []))
        unattributed_ok = bool(ent.get("unattributed_ok"))
        quiet = ent.get("quiet_hours")
        url = ("/api/history/period/"
               f"{urllib.parse.quote(start.isoformat())}"
               f"?filter_entity_id={eid}"
               f"&end_time={urllib.parse.quote(end.isoformat())}")
        try:
            data = ha_get(base, token, url)
        except Exception as e:
            deltas.append(f"{eid}: history fetch failed: {e}")
            continue
        rows = (data or [[]])[0]
        changes = []
        prev = None
        for s in rows:
            if s["state"] != prev and prev is not None:
                changes.append(s)
            prev = s["state"]
        unattr, quiet_hits = [], []
        for s in changes:
            ctx = s.get("context") or {}
            by = ctx.get("user_id") or ctx.get("parent_id") or ""
            attributed = bool(by) and (
                by in allowed_users or by in allowed_callers or
                any(by in v for v in (allowed_users, allowed_callers)))
            ts = datetime.fromisoformat(s["last_changed"]).astimezone()
            line = (f"{eid} {prev}->{s['state']} at "
                    f"{ts.strftime('%m-%d %H:%M')}")
            if quiet and _in_quiet(ts, quiet) and not attributed:
                quiet_hits.append(line + " (quiet-hours, no commander)")
            elif not attributed and not unattributed_ok:
                unattr.append(line)
        for h in quiet_hits[:10]:
            deltas.append(f"UNEXPLAINED: {h}")
        for u in unattr[:10]:
            deltas.append(f"UNEXPLAINED: {u}")
        if len(changes) > int(ent.get("max_changes_per_day", 60)):
            deltas.append(f"FLAP: {eid} changed {len(changes)} times in "
                          f"{hours}h (max {ent['max_changes_per_day']})")
    return deltas


def emit_card(deltas: list[str]) -> str:
    path = CARDS_DIR / f"{CARD_ID}.yml"
    today = time.strftime("%Y-%m-%d")
    def load():
        try:
            return yaml.safe_load(path.read_text()) or {}
        except Exception:
            return {}
    card = load()
    if not deltas:
        if path.exists() and card.get("column") == "review":
            card["column"] = "done"
            card["note"] = f"Auto-recovered {today}: all watched entities attributed."
            card["updated"] = today
            path.write_text(yaml.safe_dump(card, sort_keys=False,
                                           allow_unicode=True))
            return "closed"
        return "clean"
    card.update({
        "id": CARD_ID,
        "title": f"Command-truth: {len(deltas)} unattributed device "
                 "state change(s)",
        "brief": ("A watched device changed state with no allowlisted "
                  "commander — attribute it (logbook context, unit, "
                  "automation, device-side schedule) then either fix the "
                  "commander or add it to ssot.command-truth.yml "
                  "allowed_commanders."),
        "column": "review",
        "review_kind": "triage",
        "generated": "command-truth",
        "program": "chaba-ci",
        "area": "ha-ops",
        "priority": "high",
        "note": "\n".join(f"- {d}" for d in deltas)[:1400],
        "help": ("config: docs/ssot/infrastructure/ssot.command-truth.yml. "
                 "context.user_id = HA user/API caller; parent_id = "
                 "automation/script run; neither = device-side schedule, "
                 "integration poll, or LAN chatter."),
        "updated": today,
    })
    if card == load():
        return "unchanged"
    path.write_text(yaml.safe_dump(card, sort_keys=False, allow_unicode=True))
    return "updated"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", action="store_true")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--ssot", type=Path, default=SSOT)
    args = ap.parse_args()

    cfg = yaml.safe_load(args.ssot.read_text())
    ha = cfg["instance"]
    token_file = Path(ha["token_file"]).expanduser()
    token = ""
    for line in token_file.read_text().splitlines():
        if line.startswith("HASS_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
    deltas = audit(ha["base_url"], token, cfg, args.hours)
    for d in deltas:
        print(f"  - {d}")
    if not deltas:
        print("All watched state changes attributed.")
    if args.cards:
        print(f"{CARD_ID}: {emit_card(deltas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
