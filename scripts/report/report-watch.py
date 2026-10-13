#!/usr/bin/env python3
"""report-watch — the report graph's consumer.

Walks ssot.reports.yml nodes, reads each meta.yml, and raises a
focus-inbox item when a node needs a human/agent:

  error   — generator crashed (immediate)
  missing — declared node never produced meta (immediate)
  stale   — meta.generated_at older than the node's cadence (immediate —
            stale is already a lag). Computed HERE: producers write
            ok|delta; cadence enforcement is the consumer's job.
  delta   — findings present AND unchanged >24h (a delta that never
            clears is a finding nobody looked at; fresh deltas are
            routine drift — audit-hosts is delta most of the time)
  overrun — meta.extra.chars exceeds the node's declared hard limit
            (informational: a rendered surface outgrew its budget —
            focus-inbox note, never a page)

One inbox item per node while the bad state persists (dedupe by slug,
only unprocessed items count); state.json records when each bad state
was first seen. Flags auto-close (focus.status: processed) when the
node heals — the inbox stays a review queue, not an archive.

Also re-probes `expected_goals` on done kanban cards every GOAL_PROBE_H
hours — a pass at close proves nothing about next month; regressions
raise a `report-watch-goal-rot-<card>` inbox item.

Usage: report-watch.py [--quiet] [--json] [--dry-run] [--gate]
  --json    machine-readable report of every node + flags on stdout
  --dry-run compute everything, write nothing (no inbox items, no heal
            flips, no card requeue, no state.json)
  --gate    exit 1 while any node sits in a flag-worthy state — the CI
            gate (e.g. `report-watch.py --json --dry-run --gate`)
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
import report as rlib  # scripts/lib/report.py — cadence + artifact helpers


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


def _item_tag(raw: str) -> str:
    """Inbox filename substring for a flag — 'x-overrun'/'goal-rot-x'
    become report-watch-x-overrun / report-watch-goal-rot-x."""
    return raw if raw.startswith("report-watch-") \
        else f"report-watch-{slug(raw)}"


def open_item(raw: str) -> Path | None:
    """First OPEN (unprocessed) inbox file carrying this flag's tag.
    Items already flipped to focus.status processed/archived don't
    count — a healed flag that rots again must re-flag, not stay muted."""
    tag = _item_tag(raw)
    if not INBOX.is_dir():
        return None
    for p in sorted(INBOX.iterdir()):
        if not p.is_file() or p.name.startswith(("processed", "archived")):
            continue
        # a node flag must not match its own overrun item — the slug is a
        # strict prefix (report-watch-<nid>-overrun contains the tag)
        if "-overrun" not in tag and "-overrun" in p.name:
            continue
        if tag not in p.name:
            continue
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        st = str((doc.get("focus") or {}).get("status") or "draft")
        if st in ("processed", "archived", "completed"):
            continue
        return p
    return None


def heal_item(raw: str, reason: str, dry_run: bool) -> str | None:
    """Auto-close an open flag whose condition cleared — the item's own
    text promises 'clears once the node reports ok'. Returns the healed
    filename for reporting, None when nothing was open."""
    p = open_item(raw)
    if not p:
        return None
    if not dry_run:
        try:
            doc = yaml.safe_load(p.read_text()) or {}
            foc = doc.setdefault("focus", {})
            foc["status"] = "processed"
            foc["processed_reason"] = reason
            p.write_text(yaml.safe_dump(doc, sort_keys=False,
                                        allow_unicode=True, width=120))
        except Exception:
            return None
    return p.name


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


def make_overrun_item(node: dict, chars: float, hard: float) -> dict:
    nid = node["id"]
    return {
        "title": "Focus Inbox Item",
        "subtitle": f"Report node {nid} exceeded its hard budget",
        "focus": {
            "label": f"Report watch: {nid} over budget",
            "text": (f"Rendered surface `{nid}` is {int(chars):,} chars — "
                     f"over its declared hard limit of {int(hard):,} "
                     "(meta.extra.chars > limits.hard in ssot.reports.yml).\n\n"
                     "The bounded_surfaces standard expects the producer "
                     "to enforce the budget itself, so an overrun means "
                     "the render isn't going through scripts/lib/bounded.py "
                     "or the declared limit is wrong.\n\n"
                     f"Meta: {node.get('meta')}\n\n"
                     "Fix the producer to render through bounded.py, or "
                     "raise the declared limit if the surface is "
                     "legitimately that large. Informational — no page."),
            "status": "draft",
            "priority": "low",
            "tags": ["report", "watch", "overrun"],
            "missing_info": [
                "Producer not enforcing its budget, or a limit that no longer fits the surface?",
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


def probe_done_goals(state: dict, now, quiet: bool, dry_run: bool,
                     healed: list) -> list[str]:
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
            h = heal_item(f"goal-rot-{slug(cid)}",
                          f"healed — expected_goals probe passed "
                          f"{now.strftime('%Y-%m-%d %H:%M')}", dry_run)
            if h:
                healed.append(h)
            continue
        # on_goal_rot: requeue — loop the regression back into the board
        # instead of an inbox item: stamp the failure evidence on the
        # card (flock protocol, same as kanban-dispatch) then requeue via
        # the API so comms + column transition stay consistent.
        if card.get("on_goal_rot") == "requeue" and not dry_run \
                and rot_requeue(p, cid, failed):
            if not quiet:
                print(f"goal-rot {cid}: requeued")
            continue
        if open_item(f"goal-rot-{slug(cid)}"):
            continue
        if not dry_run:
            fname = (f"{now.strftime('%Y-%m-%d-%H%M%S')}-"
                     f"report-watch-goal-rot-{slug(cid)}.yml")
            (INBOX / fname).write_text(yaml.safe_dump(
                make_goalrot_item(cid, failed),
                sort_keys=False, allow_unicode=True, width=120))
        if not quiet:
            print(f"flagged goal-rot {cid}")
    return probed


def node_status(node: dict, now) -> dict:
    """Observed status for one registry node — the consumer's view.

    Producers write ok|delta|error|unreachable; this function derives the
    rest: `stale` from generated_at vs the node's declared cadence (the
    cadence_enforcement contract — producers never self-declare stale),
    `untracked`/`missing`/`dormant` for meta-less nodes."""
    mp = meta_path(node)
    meta, meta_state = {}, "absent"
    if mp and mp.is_file():
        try:
            meta = yaml.safe_load(mp.read_text()) or {}
            meta_state = "ok"
        except Exception:
            meta_state = "unreadable"
    gen = str(node.get("generator") or "")
    dormant = gen.lstrip().startswith("planned") or "<" in gen

    if node.get("state") == "planned":
        status = "planned"     # registered intent, generator not built
    elif meta_state == "unreadable":
        status = "error"
    elif meta_state == "ok":
        status = meta.get("status") or "ok"
    elif mp is None:
        status = None  # no meta declared — nothing to observe
    elif rlib.latest_artifact(node.get("output"),
                              node.get("artifact_pattern")):
        status = "untracked"   # artifacts but no meta — legacy producer
    elif node.get("observe") == "remote":
        status = "remote"      # meta lives off this checkout (push-back)
    elif dormant:
        status = "dormant"     # arg-required / planned — exempt pre-run
    else:
        status = "missing"

    # stale is observed, never self-declared: a fresh-once meta that
    # stopped landing reads stale once generated_at outlives cadence
    if status in ("ok", "delta"):
        cadence_s = rlib.parse_cadence(node.get("cadence"))
        age_h = _iso_age_h(meta.get("generated_at"), now)
        if cadence_s and age_h is not None and age_h * 3600 > cadence_s:
            status = "stale"

    # offline_ok nodes tolerate unreachable (laptops sleep, travel
    # hosts leave the tailnet); an unreachable server still flags
    offline_ok = bool(node.get("offline_ok"))
    return {"status": status, "meta": meta, "meta_path": mp,
            "summary": str(meta.get("summary") or ""),
            "generated_at": meta.get("generated_at"),
            "dormant": dormant, "offline_ok": offline_ok}


def main() -> int:
    as_json = "--json" in sys.argv
    # --json stdout is the machine contract — keep chatter off it
    quiet = "--quiet" in sys.argv or as_json
    dry_run = "--dry-run" in sys.argv
    gate = "--gate" in sys.argv
    reg = yaml.safe_load(REGISTRY.read_text())
    nodes = reg.get("nodes") or []
    state = load_state()
    now = datetime.now(timezone(timedelta(hours=7)))
    now_s = now.strftime("%Y-%m-%d %H:%M:%S +07")

    created, healed, report_rows, active = [], [], [], []
    for node in nodes:
        nid = node["id"]
        obs = node_status(node, now)
        status = obs["status"]
        meta = obs["meta"]

        # overrun — informational only: the rendered surface's recorded
        # char count exceeded its declared hard limit. Independent of
        # status (a node can be ok AND over budget); slug-deduped like
        # the status flags.
        hard = (node.get("limits") or {}).get("hard")
        chars = (meta.get("extra") or {}).get("chars")
        over = (isinstance(hard, (int, float)) and not isinstance(hard, bool)
                and isinstance(chars, (int, float)) and not isinstance(chars, bool)
                and chars > hard)
        oid = f"{nid}-overrun"
        if over:
            if not open_item(oid):
                created.append(f"{nid}=overrun")
                if not dry_run:
                    fname = (f"{now.strftime('%Y-%m-%d-%H%M%S')}-"
                             f"report-watch-{slug(oid)}.yml")
                    (INBOX / fname).write_text(yaml.safe_dump(
                        make_overrun_item(node, chars, hard),
                        sort_keys=False, allow_unicode=True, width=120))
            if not quiet:
                print(f"overrun {nid}: {int(chars):,} chars > hard {int(hard):,}")
        else:
            h = heal_item(oid, f"healed — rendered surface back under "
                               f"the {int(hard):,}-char limit", dry_run) \
                if isinstance(hard, (int, float)) \
                and not isinstance(hard, bool) else None
            if h:
                healed.append(h)

        key = slug(nid)
        prev = state.get(key) or {}
        if status != prev.get("status"):
            state[key] = {"status": status, "first_seen": now_s}
            prev = state[key]
        first_seen = prev.get("first_seen", now_s)

        flag = False
        if status in BAD_NOW:
            flag = True
        elif status in BAD_SUSTAINED and not (status == "unreachable"
                                              and obs["offline_ok"]):
            try:
                seen = datetime.strptime(first_seen, "%Y-%m-%d %H:%M:%S %z")
                flag = (now - seen) > timedelta(hours=DELTA_GRACE_H)
            except Exception:
                flag = False
        report_rows.append({
            "node": nid, "status": status, "first_seen": first_seen,
            "flagged": flag, "generated_at": obs["generated_at"],
            "summary": obs["summary"][:160]})
        if flag:
            active.append(f"{nid}={status}")
            if not open_item(nid):
                created.append(f"{nid}={status}")
                if not dry_run:
                    fname = (f"{now.strftime('%Y-%m-%d-%H%M%S')}-"
                             f"report-watch-{key}.yml")
                    (INBOX / fname).write_text(yaml.safe_dump(
                        make_item(node, status, obs["summary"],
                                  first_seen),
                        sort_keys=False, allow_unicode=True, width=120))
                if not quiet:
                    print(f"flagged {nid} ({status}, since {first_seen})")
        else:
            h = heal_item(nid, f"healed — node reports {status} "
                               f"({now.strftime('%Y-%m-%d %H:%M')})",
                          dry_run)
            if h:
                healed.append(h)

    probed = probe_done_goals(state, now, quiet, dry_run, healed)
    if not dry_run:
        save_state(state)
    summary = (f"report-watch: {len(nodes)} nodes, {len(created)} flagged"
               + (f" ({', '.join(created)})" if created else "")
               + f", {len(healed)} healed, {len(probed)} goal-probes")
    if as_json:
        print(json.dumps({
            "at": now.isoformat(timespec="seconds"),
            "nodes": report_rows,
            "flagged": created, "active_flags": active,
            "healed": healed, "goal_probes": probed,
            "dry_run": dry_run}, indent=1))
    else:
        print(summary)
    return 1 if (gate and active) else 0


if __name__ == "__main__":
    sys.exit(main())
