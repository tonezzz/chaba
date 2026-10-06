#!/usr/bin/env python3
"""kanban-act.py — the T2 layer: Chaba pushes the button, with receipts.

Cards declare their own automation contract:

    autonomy: t2                    # absent/t1 = suggest-only, t3 = human-only
    auto_done_when:                 # ALL must pass — deterministic checks only
      - page_exists:kanban-brief
      - service_active:chaba-kanban-brief.timer@tony-dell
      - card_done:some-other-card
      - file_exists:scripts/ada/kanban-brief.py
    done_note: why this counts as done   # written into the card note

When every check passes, the card file gets column: done + a `verified:
auto <ts>` line and the card's note gains the done_note. Nothing else is
touched. Every action emits a kanban_act ops event (ada-ha-events-tony)
so the digest audits each autonomous move. Cap: MAX_ACTS per run.

Check kinds are the whole vocabulary — no arbitrary commands ever:

    page_exists:<slug>            CMS page exists
    card_done:<id>                named card is column:done
    file_exists:<repo-path>       path exists under the checkout
    service_active:<unit>@<host>  ssh systemctl --user is-active

Runs from the chaba-tony-dell checkout (single-writer rule) — the
kanban-commit timer persists the card edits.

Env:
    MDDB_BASE_URL    default http://100.102.134.91:11023/v1
    REPO             default = this checkout root
    KANBAN_ACT_MAX   default 5 — cap on autonomous actions per run

Usage:
    kanban-act.py            # evaluate + act
    kanban-act.py --dry-run  # report what would act, change nothing
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
CARDS_DIR = REPO / "docs/ssot/kanban/cards"
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
OPS_COLLECTION = "ada-ha-events-tony"
MAX_ACTS = int(os.environ.get("KANBAN_ACT_MAX", "5"))

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.~-]+$")


# ---------- checks ----------

def check_card_done(arg: str, by_id: dict[str, dict]) -> bool:
    c = by_id.get(arg)
    return bool(c) and c.get("column") == "done"


def check_file_exists(arg: str, _by_id) -> bool:
    p = (REPO / arg).resolve()
    return p.exists() and str(p).startswith(str(REPO.resolve()))


def check_service_active(arg: str, _by_id) -> bool:
    unit, _, host = arg.partition("@")
    if not unit or not host or not _SAFE_ID.match(host):
        return False
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host,
             f"systemctl --user is-active {unit}"],
            capture_output=True, text=True, timeout=15)
        return out.stdout.strip() == "active"
    except Exception:
        return False


def check_page_exists(arg: str, _by_id) -> bool:
    try:
        docs = _post("search", {"collection": "ada-cms-pages",
                                "query": "", "limit": 500})
        return any(d.get("key") == arg for d in docs)
    except Exception:
        return False


CHECKS = {
    "card_done": check_card_done,
    "file_exists": check_file_exists,
    "service_active": check_service_active,
    "page_exists": check_page_exists,
}


def _post(path, payload, timeout=30):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _ops_event(detail: str) -> None:
    """kanban_act audit line — lands in the ada ops digest."""
    try:
        now = datetime.now(timezone.utc)
        _post("add", {
            "collection": OPS_COLLECTION,
            "key": f"ops-kanban-act-{now:%Y%m%d%H%M%S%f}",
            "lang": "en", "contentMd": detail,
            "meta": {"kind": ["ops-event"], "type": ["kanban_act"],
                     "instance": ["tony"],
                     "ts": [now.isoformat(timespec="seconds")],
                     "written_by": ["kanban-act"]}})
    except Exception as e:
        print(f"warn: ops event failed: {e}", file=sys.stderr)


# ---------- card edit ----------

def mark_done(path: Path, card: dict, results: list[tuple[str, bool]]) -> None:
    """Surgical yaml rewrite: set column: done, stamp verified, append
    done_note. We edit the file text-wise so comments/other fields keep
    their formatting."""
    text = path.read_text()
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    if not re.search(r"^column:", text, re.M):
        raise ValueError(f"{path.name}: no column field")
    text = re.sub(r"^column:.*$", "column: done", text, count=1,
                  flags=re.M)
    if re.search(r"^verified:", text, re.M):
        text = re.sub(r"^verified:.*$", f"verified: 'auto {now}'",
                      text, count=1, flags=re.M)
    else:
        text = text.rstrip() + f"\nverified: 'auto {now}'\n"
    note = (card.get("done_note") or
            "auto-closed by kanban-act: all auto_done_when checks passed")
    text += (f"auto_close:\n  by: kanban-act\n  at: '{now}'\n"
             f"  note: >-\n    {note}\n  checks:\n"
             + "".join(f"    - '{expr} -> {'pass' if ok else 'fail'}'\n"
                       for expr, ok in results))
    path.write_text(text)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cards = []
    for f in sorted(CARDS_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        c["_file"] = f
        cards.append(c)
    by_id = {c.get("id") or c["_file"].stem: c for c in cards}

    acted = considered = 0
    for c in cards:
        if (c.get("autonomy") or "t1").lower() != "t2":
            continue
        when = c.get("auto_done_when") or []
        if c.get("column") == "done" or not when:
            continue
        considered += 1
        results = []
        all_ok = True
        for expr in when:
            kind, _, arg = expr.partition(":")
            fn = CHECKS.get(kind)
            if fn is None:
                results.append((expr, False))
                all_ok = False
                break
            try:
                ok = fn(arg, by_id)
            except Exception:
                ok = False
            results.append((expr, ok))
            if not ok:
                all_ok = False
        cid = c.get("id") or c["_file"].stem
        if not all_ok:
            print(f"[hold] {cid}: "
                  f"{[f'{e}={o}' for e, o in results]}")
            continue
        if acted >= MAX_ACTS:
            print(f"[cap] {cid}: MAX_ACTS reached — deferred")
            continue
        if args.dry_run:
            print(f"[would-act] {cid}: all {len(results)} checks pass")
            acted += 1
            continue
        mark_done(c["_file"], c, results)
        _ops_event(
            f"kanban-act closed `{cid}` — auto_done_when "
            f"{len(results)}/{len(results)} passed")
        print(f"[acted] {cid} -> done "
              f"({', '.join(e for e, _ in results)})")
        acted += 1

    print(f"kanban-act: {considered} t2 cards evaluated, "
          f"{acted} auto-closed"
          + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
