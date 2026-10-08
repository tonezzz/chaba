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

Also re-probes `expected_goals` on done kanban cards every GOAL_PROBE_H
hours — a pass at close proves nothing about next month; regressions
raise a `report-watch-goal-rot-<card>` inbox item.

Usage: report-watch.py [--quiet]
"""
import fcntl
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "docs/ssot/infrastructure/ssot.reports.yml"
INBOX = REPO / "docs/ssot/focus-inbox"
CARDS = REPO / "docs/ssot/kanban/cards"
STATE = REPO / "reports/report-watch/state.json"
DELTA_GRACE_H = 24
GOAL_PROBE_H = 24  # done-card expected_goals re-probe interval

BAD_NOW = {"error", "missing", "stale"}
BAD_SUSTAINED = {"delta", "unreachable"}

sys.path.insert(0, str(REPO / "scripts" / "lib"))
try:
    import goals as goallib  # scripts/lib/goals.py — expected_goals checks
except Exception:  # pragma: no cover - re-probe optional
    goallib = None


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


def _iso_age_h(value, now) -> float | None:
    """Hours since an ISO/“YYYY-MM-DD HH:MM” timestamp; None if absent
    or unparseable."""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).strip().replace(" ", "T"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.astimezone()
    return (now - t).total_seconds() / 3600


def make_goalrot_item(cid: str, failed: list) -> dict:
    lines = "\n".join(f"  - {r['id']}: {r.get('evidence', '')[:140]}"
                      for r in failed[:6])
    return {
        "title": "Focus Inbox Item",
        "subtitle": f"Done card {cid} has failing expected_goals",
        "focus": {
            "label": f"Goal rot: {cid}",
            "text": (f"Done card `{cid}` keeps `expected_goals` and a "
                     f"scheduled re-probe found {len(failed)} failing — "
                     f"the work passed at close but has since rotted:\n\n"
                     f"{lines}\n\n"
                     "Fix the regression, update the goal (reality moved), "
                     "or drop expected_goals from the card. The item "
                     "clears once a probe passes."),
            "status": "draft",
            "priority": "medium",
            "tags": ["report", "watch", "goal-rot"],
            "missing_info": [
                "Real regression, or a goal describing a world that moved on?",
            ],
        },
    }


BOARD_LOCK = Path(os.environ.get("BOARD_LOCK", "/tmp/board-api.lock"))
BOARD_API = os.environ.get("BOARD_API", "http://127.0.0.1:8787").rstrip("/")


def rot_requeue(card_path: Path, cid: str, failed: list) -> bool:
    """on_goal_rot:requeue — stamp the rot evidence on the card under the
    shared flock, then do=queue via board-api (status queued, column ->
    backlog, comms line). Returns True when the requeue was accepted."""
    detail = ("goal rot — expected_goals failing on done card: "
              + ", ".join(r["id"] for r in failed[:5]))[:280]
    try:
        with BOARD_LOCK.open("w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            card = yaml.safe_load(card_path.read_text()) or {}
            a = card.setdefault("action", {})
            if a.get("status") == "queued":
                return True  # already looped back
            a["last_failure"] = detail
            card_path.write_text(yaml.safe_dump(
                card, sort_keys=False, allow_unicode=True, width=120))
    except Exception:
        return False
    try:
        req = urllib.request.Request(
            BOARD_API + "/action",
            data=json.dumps({"id": cid, "do": "queue",
                             "from": "chaba"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        return not resp.get("error")
    except Exception:
        return False


def probe_done_goals(state: dict, now, quiet: bool) -> list[str]:
    """Re-probe expected_goals on done cards — a pass at close proves
    nothing about next month. Due when neither report-watch's own probe
    nor the card's pipeline.verify result is younger than GOAL_PROBE_H.
    Failures raise one focus-inbox item per card (slug-deduped); probe
    results persist in state.json."""
    if goallib is None or not CARDS.is_dir():
        return []
    probed = []
    for p in sorted(CARDS.glob("*.yml")):
        try:
            card = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if card.get("column") != "done":
            continue
        goals, _ = goallib.validate_goals(card)
        if not goals:
            continue
        cid = str(card.get("id") or p.stem)
        key = f"goalprobe-{cid}"
        last = (state.get(key) or {}).get("at")
        if not last:
            pipe = card.get("pipeline")
            if isinstance(pipe, dict):
                last = (pipe.get("verify") or {}).get("at")
        age = _iso_age_h(last, now)
        if age is not None and age < GOAL_PROBE_H:
            continue
        results = goallib.run_goals(goals, REPO)
        failed = [r for r in results if r["ok"] is not True]
        state[key] = {"at": now.isoformat(timespec="seconds"),
                      "ok": f"{len(results) - len(failed)}/{len(results)}"}
        probed.append(cid)
        if not quiet:
            print(f"goal-probe {cid}: {state[key]['ok']}"
                  + (f" FAIL: {', '.join(r['id'] for r in failed[:4])}"
                     if failed else ""))
        if not failed:
            continue
        # on_goal_rot: requeue — loop the regression back into the board
        # instead of an inbox item: stamp the failure evidence on the
        # card (flock protocol, same as kanban-dispatch) then requeue via
        # the API so comms + column transition stay consistent.
        if card.get("on_goal_rot") == "requeue" and rot_requeue(
                p, cid, failed):
            if not quiet:
                print(f"goal-rot {cid}: requeued")
            continue
        if inbox_exists(f"goal-rot-{slug(cid)}"):
            continue
        fname = (f"{now.strftime('%Y-%m-%d-%H%M%S')}-"
                 f"report-watch-goal-rot-{slug(cid)}.yml")
        (INBOX / fname).write_text(yaml.safe_dump(
            make_goalrot_item(cid, failed),
            sort_keys=False, allow_unicode=True, width=120))
        if not quiet:
            print(f"flagged goal-rot {cid}")
    return probed


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

    probed = probe_done_goals(state, now, quiet)
    save_state(state)
    print(f"report-watch: {len(nodes)} nodes, {len(created)} flagged"
          + (f" ({', '.join(created)})" if created else "")
          + f", {len(probed)} goal-probes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
