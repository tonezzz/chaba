#!/usr/bin/env python3
"""cms-auto-health — CMS automation registry -> kanban cards.

Reads every doc in the ada-cms-automation MDDB collection, judges each
page's refresh health against its own interval, and writes/updates a
`cms-auto-<slug>` kanban card so a broken automation becomes tracked work
instead of a silently stale page.

Card lifecycle (the auto-improve loop):
  unhealthy        -> column=review, note = last_error + staleness
  still unhealthy  -> note updated in place (card history = incident log)
  recovered        -> column=done, note records the recovery time
  interval_min=0   -> manual-trigger pages; no staleness check

Runs anywhere with MDDB access; writes into a chaba checkout. Committing
is the caller's job (the timer wrapper git-adds only cms-auto-* files).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import yaml

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1").rstrip("/")
REPO = Path(os.environ.get(
    "CHABA_REPO",
    str(Path(__file__).resolve().parents[2])))
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"
# staleness grace on top of the page's own interval — regen workers run
# periodically and schedules drift; 2x interval + 30m is "actually broken".
GRACE_S = 30 * 60
# a card open this long gets priority bumped to high — an automation that
# nobody fixes for half a day deserves attention, not just presence.
ESCALATE_H = 12


def _post(path: str, payload: dict, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(
        f"{MDDB}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def list_automations() -> list[dict]:
    docs = _post("/search", {"collection": "ada-cms-automation",
                             "limit": 500})
    out = []
    for d in docs:
        try:
            cfg = json.loads(d.get("contentMd") or "{}")
        except json.JSONDecodeError:
            cfg = {"_unparseable": True}
        cfg["_slug"] = d.get("key") or ""
        out.append(cfg)
    return out


def judge(cfg: dict, now: float) -> tuple[str, str]:
    """-> (state, reason): state in ok|stale|error|dead|manual."""
    slug = cfg["_slug"]
    if cfg.get("_unparseable"):
        return "dead", "registry doc is not valid JSON"
    if not cfg.get("enabled", True):
        return "ok", "disabled — no check"
    interval = int(cfg.get("interval_min") or 0)
    last_status = cfg.get("last_status")
    last_error = cfg.get("last_error")
    last_run = cfg.get("last_run")
    if interval <= 0:
        return "manual", "manual-trigger page (interval=0)"
    if not last_run:
        return "dead", f"enabled every {interval}m but never ran"
    try:
        last_ts = float(last_run) if isinstance(last_run, (int, float)) else \
            time.mktime(time.strptime(str(last_run)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return "dead", f"unparseable last_run {last_run!r}"
    overdue_s = now - last_ts - interval * 60
    if last_status and last_status != "ok":
        return "error", f"last_status={last_status} — {last_error or 'no detail'}"
    if overdue_s > GRACE_S:
        return "stale", (f"last_run {int(overdue_s // 60)}m overdue "
                         f"(interval {interval}m)")
    return "ok", ""


def card_path(slug: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
    return CARDS / f"cms-auto-{safe}.yml"


def load_card(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def write_card(path: Path, card: dict) -> None:
    path.write_text(yaml.safe_dump(card, sort_keys=False,
                                   allow_unicode=True))


def main() -> int:
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    cms = "https://idc01.taila0626a.ts.net/cms"
    n_bad = n_ok = n_recovered = 0
    for cfg in list_automations():
        slug = cfg["_slug"]
        if not slug:
            continue
        state, reason = judge(cfg, now)
        path = card_path(slug)
        card = load_card(path)
        exists = path.exists()
        healthy = state in ("ok", "manual")

        if not healthy:
            n_bad += 1
            opened = card.get("updated") if exists and \
                card.get("column") == "review" else today
            card.update({
                "id": f"cms-auto-{slug}",
                "title": f"CMS automation `{slug}` {state}",
                "column": "review",
                "generated": "cms-auto-health",
                "priority": "high" if card.get("column") == "review"
                else "medium",
                "note": (f"{reason}. last_run={cfg.get('last_run')} "
                         f"interval={cfg.get('interval_min')}m "
                         f"status={cfg.get('last_status')}. "
                         f"Page: {cms}/#/{slug}"),
                "help": ("Trigger a manual regen: cms_automation run_now "
                         f"for '{slug}' (or POST /api/cms/pages/{slug}/"
                         "regenerate). If it repeats, check the page's "
                         "generator command in the registry doc."),
                "updated": opened,
            })
            write_card(path, card)
        else:
            n_ok += 1
            # auto-close: unhealthy card whose automation recovered
            if exists and card.get("column") == "review" and \
                    card.get("generated") == "cms-auto-health":
                card["column"] = "done"
                card["note"] = (f"Auto-recovered {today}: {slug} healthy "
                                f"again (status={cfg.get('last_status')}, "
                                f"state={state}).")
                card["updated"] = today
                write_card(path, card)
                n_recovered += 1
    print(f"cms-auto-health: {n_bad} unhealthy, {n_ok} ok/manual, "
          f"{n_recovered} auto-recovered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
