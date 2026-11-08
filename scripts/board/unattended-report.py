#!/usr/bin/env python3
"""unattended-report — the daily hands-off digest (KNB-0928).

Once a day (chaba-unattended-report.timer on the writer host) this scans
the card board for everything the unattended lanes touched or is holding,
evaluates each queued/starting card through the waiting_cards gate, and
emits:

  1. reports/unattended-<YYYY-MM-DD>.md — the durable record
     (claims/finishes/fails/stalls from card comms + action fields,
     gate verdicts, preflight state)
  2. a /publish milestone to board-api — fans out to Telegram through
     the server-side noise policy (one concise notification/day)

Read-only by design: it never mutates cards. Run manually with
--dry-run to preview; --json for machine output.

Usage:
    unattended-report.py [--dry-run] [--json] [--api URL]

Env:
    KANBAN_PUBLISH_API   board-api base (default http://127.0.0.1:8787)
    UNATTENDED_REPORT_DIR  report output dir (default <repo>/reports)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import waiting_cards as wc

REPO = Path(__file__).resolve().parents[2]
CARDS_DIR = REPO / "docs/ssot/kanban/cards"
REPORT_DIR = Path(os.environ.get(
    "UNATTENDED_REPORT_DIR", str(REPO / "reports")))
PUBLISH_API = os.environ.get(
    "KANBAN_PUBLISH_API", "http://127.0.0.1:8787").rstrip("/")
ICT = timezone(timedelta(hours=7))


def _load(path: Path) -> dict:
    try:
        c = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}
    c.setdefault("id", path.stem)
    return c


def _today() -> str:
    return datetime.now(ICT).strftime("%Y-%m-%d")


def _day(card: dict) -> str:
    u = str(card.get("updated") or "")
    return u[:10]


def collect() -> dict:
    """Board snapshot for the digest."""
    cards = []
    for f in sorted(CARDS_DIR.glob("*.yml")):
        c = _load(f)
        if not c.get("id"):
            continue
        a = c.get("action") or {}
        st = str(a.get("status") or "").lower()
        if st in ("queued", "starting", "running", "held") \
                or _day(c) == _today():
            cards.append(c)
    env = wc.local_env()
    verdicts = [wc.evaluate(c, env=env) for c in cards
                if str((c.get("action") or {}).get("status") or "")
                in ("queued", "starting")]
    return {"cards": cards, "verdicts": verdicts, "env": env}


def render(snap: dict) -> str:
    today = _today()
    cards = snap["cards"]
    verdicts = snap["verdicts"]
    env = snap["env"]

    by_status: dict = {}
    for c in cards:
        st = str((c.get("action") or {}).get("status") or "-")
        by_status[st] = by_status.get(st, 0) + 1

    lines = [
        f"# Unattended-run digest — {today}",
        "",
        f"Generated {datetime.now(ICT):%Y-%m-%d %H:%M} ICT by "
        "scripts/board/unattended-report.py (KNB-0928).",
        "",
        "## Preflight (this host)",
        "",
        f"- kill switch `{wc.KILL_SWITCH}`: "
        f"{'PRESENT — claims frozen' if env['kill_switch'] else 'absent'}",
        f"- deploy lock `{wc.DEPLOY_LOCK}`: "
        f"{'HELD' if env['deploy_lock'] else 'free'}",
        f"- disk free on {env['disk_path']}: "
        f"{env['disk_free_mb']:.0f} MB (floor {env['disk_min_mb']:.0f})",
        f"- backup proof (R2 gate): "
        f"{env.get('backup_proof') or 'unset — R2 cards defer'}",
        "",
        "## Queue snapshot",
        "",
        "- " + (", ".join(f"{k or 'none'}: {v}" for k, v in
                        sorted(by_status.items())) or "no active cards"),
        "",
        "## waiting_cards verdicts (queued/starting)",
        "",
    ]
    if verdicts:
        for v in verdicts:
            mark = "ELIGIBLE" if v["eligible"] else (
                "NEVER-AUTONOMOUS" if v["never"] else "HOLD")
            lines.append(f"- [{mark}] `{v['id']}` "
                         f"(recoverability={v['recoverability'] or '?'}, "
                         f"autonomy={v['autonomy']})")
            for r in v["reasons"]:
                lines.append(f"  - {r}")
    else:
        lines.append("- no queued/starting cards")

    n_ok = sum(1 for v in verdicts if v["eligible"])
    n_never = sum(1 for v in verdicts if v["never"])
    lines += [
        "",
        "## Activity today (cards updated " + today + ")",
        "",
    ]
    today_cards = [c for c in cards if _day(c) == today]
    if today_cards:
        for c in today_cards[:40]:
            a = c.get("action") or {}
            lines.append(
                f"- `{c['id']}` — column={c.get('column')}, "
                f"status={a.get('status') or '-'}, "
                f"recoverability={c.get('recoverability') or '-'}")
        if len(today_cards) > 40:
            lines.append(f"- … and {len(today_cards) - 40} more")
    else:
        lines.append("- none")

    lines += [
        "",
        "## Metrics",
        "",
        f"- queued/starting evaluated: {len(verdicts)}",
        f"- eligible: {n_ok} · held: {len(verdicts) - n_ok - n_never} "
        f"· never-autonomous: {n_never}",
        f"- cards touched today: {len(today_cards)}",
        "",
    ]
    return "\n".join(lines)


def publish_digest(today: str, md: str) -> bool:
    """One milestone event -> Telegram via /publish fan-out."""
    n_elig = md.count("[ELIGIBLE]")
    n_hold = md.count("[HOLD]")
    n_never = md.count("[NEVER-AUTONOMOUS]")
    kill = "KILL SWITCH ACTIVE — " if "PRESENT" in md.split(
        "## Preflight")[1].split("##")[0] else ""
    title = (f"unattended digest {today}: {n_elig} eligible, "
             f"{n_hold} held, {n_never} never-autonomous")
    body = (f"{kill}queued cards evaluated by the waiting_cards gate; "
            f"full digest at reports/unattended-{today}.md on the "
            "writer checkout.")
    ev = {"kind": "milestone", "title": title, "body": body,
          "source": "unattended-report", "confidence": "observed",
          "visibility": "members", "project": "chaba",
          "meta": {"lane": "unattended"}}
    try:
        req = urllib.request.Request(
            f"{PUBLISH_API}/publish", data=json.dumps(ev).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except Exception as e:
        print(f"warn: publish failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print the digest, write nothing, publish nothing")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--api", default=PUBLISH_API)
    args = ap.parse_args()

    snap = collect()
    md = render(snap)
    if args.json:
        print(json.dumps({"verdicts": snap["verdicts"],
                          "env": snap["env"]}, indent=2, default=str))
        return 0
    print(md)
    if args.dry_run:
        print("(dry-run — nothing written, nothing published)")
        return 0

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"unattended-{_today()}.md"
    out.write_text(md)
    print(f"wrote {out}")
    ok = publish_digest(_today(), md)
    print(f"telegram digest: {'sent' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
