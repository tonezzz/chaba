#!/usr/bin/env python3
"""report-watch — the report graph's consumer.

Walks ssot.reports.yml nodes, reads each meta.yml, and raises a
focus-inbox item when a node needs a human/agent:

  error   — generator crashed (immediate)
  missing — declared node never produced meta (immediate)
  stale   — past cadence (immediate — stale is already a lag)
  delta   — findings present AND unchanged >24h (a delta that never
            clears is a finding nobody looked at; fresh deltas are
            routine drift — audit-hosts is delta most of the time)

One inbox item per node while the bad state persists (dedupe by slug);
state.json records when each bad state was first seen.

Usage: report-watch.py [--quiet]
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "docs/ssot/infrastructure/ssot.reports.yml"
INBOX = REPO / "docs/ssot/focus-inbox"
STATE = REPO / "reports/report-watch/state.json"
DELTA_GRACE_H = 24

BAD_NOW = {"error", "missing", "stale"}
BAD_SUSTAINED = {"delta", "unreachable"}


def meta_path(node: dict) -> Path | None:
    m = node.get("meta")
    if not m:
        return None
    p = Path(str(m).replace("%h", str(Path.home())).replace("~", str(Path.home())))
    return p if p.is_absolute() else REPO / p


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(state: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def slug(node_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", node_id.lower()).strip("-")


def inbox_exists(node_id: str) -> bool:
    tag = f"report-watch-{slug(node_id)}"
    if not INBOX.is_dir():
        return False
    for p in INBOX.iterdir():
        if p.name.startswith(("processed", "archived")):
            continue
        if tag in p.name:
            return True
    return False


def make_item(node: dict, status: str, summary: str, since: str) -> dict:
    nid = node["id"]
    why = {
        "error": "the generator crashed on its last run",
        "missing": "the node is declared but has never produced a meta",
        "stale": "the last artifact is older than its cadence",
        "delta": f"findings have persisted >{DELTA_GRACE_H}h without review",
    }.get(status, status)
    return {
        "title": "Focus Inbox Item",
        "subtitle": f"Report node {nid} is {status}",
        "focus": {
            "label": f"Report watch: {nid} = {status}",
            "text": (f"Report node `{nid}` is `{status}` — {why}.\n\n"
                     f"Summary: {summary or 'n/a'}\n"
                     f"Bad state first seen: {since}\n"
                     f"Meta: {node.get('meta')}\n\n"
                     "Fix the producer or mark the node retired; "
                     "the item clears once the node reports ok."),
            "status": "draft",
            "priority": "high" if status in ("error", "missing") else "medium",
            "tags": ["report", "watch", status],
            "missing_info": [
                "Is the failure a producer bug or real findings to triage?",
                "Should the node be fixed, muted (expect_down), or retired?",
            ],
        },
    }


def main() -> int:
    quiet = "--quiet" in sys.argv
    reg = yaml.safe_load(REGISTRY.read_text())
    nodes = reg.get("nodes") or []
    state = load_state()
    now = datetime.now(timezone(timedelta(hours=7)))
    now_s = now.strftime("%Y-%m-%d %H:%M:%S +07")

    created = []
    for node in nodes:
        nid = node["id"]
        mp = meta_path(node)
        meta = {}
        if mp and mp.is_file():
            try:
                meta = yaml.safe_load(mp.read_text()) or {}
            except Exception:
                pass
        status = meta.get("status") or ("missing" if mp else None)
        summary = str(meta.get("summary") or "")
        # dormant nodes: "planned —" generators or arg-required tools
        # (e.g. card-pipeline <card-id>) — declared intent, not failures;
        # they produce meta on their first real run
        gen = str(node.get("generator") or "")
        if status == "missing" and (gen.lstrip().startswith("planned")
                                    or "<" in gen):
            continue
        # offline_ok nodes tolerate unreachable (laptops sleep, travel
        # hosts leave the tailnet); an unreachable server still flags
        if status == "unreachable" and node.get("offline_ok"):
            continue

        key = slug(nid)
        prev = state.get(key) or {}
        if status != prev.get("status"):
            state[key] = {"status": status, "first_seen": now_s}
            prev = state[key]
        first_seen = prev.get("first_seen", now_s)

        flag = False
        if status in BAD_NOW:
            flag = True
        elif status in BAD_SUSTAINED:
            try:
                seen = datetime.strptime(first_seen, "%Y-%m-%d %H:%M:%S %z")
                flag = (now - seen) > timedelta(hours=DELTA_GRACE_H)
            except Exception:
                flag = False
        if not flag or inbox_exists(nid):
            continue

        fname = (f"{now.strftime('%Y-%m-%d-%H%M%S')}-"
                 f"report-watch-{key}.yml")
        (INBOX / fname).write_text(yaml.safe_dump(
            make_item(node, status, summary, first_seen),
            sort_keys=False, allow_unicode=True, width=120))
        created.append(f"{nid}={status}")
        if not quiet:
            print(f"flagged {nid} ({status}, since {first_seen})")

    save_state(state)
    print(f"report-watch: {len(nodes)} nodes, {len(created)} flagged"
          + (f" ({', '.join(created)})" if created else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
