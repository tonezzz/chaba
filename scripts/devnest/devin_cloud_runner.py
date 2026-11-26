#!/usr/bin/env python3
"""Consume VALIDATED Devin-cloud specs and create sessions via the v3 API.

This is the launch step of the DevNest handoff pipeline:

    proposer (dry-run) -> validator (deterministic) -> THIS runner

It never mutates a board card and never writes to a queue. Dry-run is the
DEFAULT: pass --live to actually create a session and spend quota.

Guardrails (ssot.devin-autonomy.yml + DevNest capacity procedure):
  - kill switch /tmp/no-devin-cloud-handoff
  - operator-supplied daily quota headroom floor
  - one session per run by default, deduped by task_id/source_hash for 24h
  - API-valid devin_mode only (lite by default — cheapest cloud mode)
  - hard stop on out_of_quota / usage_limit_exceeded is the caller's job;
    --poll reports those status_detail values without launching anything

Credentials are read from ~/.local/share/devin/credentials.toml and never
printed. No secrets go into prompts or launch records.

Usage::

    python3 scripts/devnest/devin_cloud_runner.py --input validated.json
    python3 scripts/devnest/devin_cloud_runner.py --input validated.json --live --remaining-pct 62
    python3 scripts/devnest/devin_cloud_runner.py --poll <session_id>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
CREDENTIALS = HOME / ".local" / "share" / "devin" / "credentials.toml"
DEVIN_CONFIG = HOME / ".config" / "devin" / "config.json"
ORG_API = "https://api.devin.ai"
STATE = HOME / ".local" / "state" / "devnest" / "devin-cloud-runner-state.json"
KILL_SWITCH = Path("/tmp/no-devin-cloud-handoff")
ALLOWED_MODES = ("normal", "fast", "fusion", "lite", "ultra", "fast-ultra")
STOP_STATUSES = {"out_of_quota", "usage_limit_exceeded", "no_quota_allocation",
                 "org_usage_limit_exceeded", "user_usage_limit_exceeded",
                 "out_of_credits", "payment_declined"}
DEDUP_HOURS = 24


def token() -> str:
    text = CREDENTIALS.read_text(encoding="utf-8")
    m = re.search(r'windsurf_api_key\s*=\s*["\']?([^"\'\s]+)', text)
    if not m:
        raise RuntimeError("no Devin credential in credentials.toml")
    return m.group(1)


def org_id() -> str:
    cfg = json.loads(DEVIN_CONFIG.read_text(encoding="utf-8"))
    return cfg["devin"]["org_id"]


def api(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        ORG_API + path, data=body, method=method,
        headers={"Authorization": "Bearer " + token(),
                 "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode() or "{}")


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"launched": []}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def recent_keys(state: dict, now: datetime) -> set[str]:
    keys: set[str] = set()
    kept = []
    for entry in state.get("launched", []):
        try:
            at = datetime.fromisoformat(entry["at"])
            if (now - at).total_seconds() > DEDUP_HOURS * 3600:
                continue
        except Exception:
            continue
        kept.append(entry)
        keys.add(entry.get("task_id", ""))
        keys.add(entry.get("source_hash", ""))
    state["launched"] = kept
    return keys


def build_payload(spec: dict, mode: str) -> dict:
    prompt = str(spec.get("prompt") or "").replace("/handoff ", "", 1)
    tags = ["devnest"] + [t for t in (spec.get("tags") or []) if t != "devnest"]
    return {
        "prompt": prompt,
        "repos": [spec["repo"]],
        "devin_mode": mode,
        "title": f"{spec.get('card_ref') or spec['task_id']} — DevNest handoff",
        "tags": tags,
    }


def poll(sid: str) -> int:
    try:
        d = api("GET", f"/v3/organizations/{org_id()}/sessions/{sid}")
    except urllib.error.HTTPError as e:
        print(json.dumps({"ok": False, "http": e.code,
                          "detail": e.read().decode()[:300]}))
        return 3
    safe = {k: d.get(k) for k in ("session_id", "status", "status_detail",
                                 "acus_consumed", "on_demand_usage",
                                 "pull_requests", "updated_at")}
    safe["ok"] = True
    safe["stop_reason"] = (d.get("status_detail") if d.get("status_detail") in STOP_STATUSES else None)
    print(json.dumps(safe, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", help="validated spec JSON (accepted list)")
    ap.add_argument("--poll", help="report one session and exit; launches nothing")
    ap.add_argument("--live", action="store_true",
                    help="actually POST and spend quota (default: dry-run)")
    ap.add_argument("--limit", type=int, default=1,
                    help="sessions per run (default 1)")
    ap.add_argument("--max-per-day", type=int, default=4,
                    help="total sessions per rolling 24h (default 4 ≈ 16 quota-points at the measured 4/PR)")
    ap.add_argument("--mode", default="lite", choices=ALLOWED_MODES)
    ap.add_argument("--remaining-pct", type=float, default=None)
    ap.add_argument("--min-remaining", type=float, default=30.0)
    args = ap.parse_args()

    if args.poll:
        return poll(args.poll)
    if not args.input:
        print(json.dumps({"ok": False, "error": "--input or --poll required"}))
        return 2

    now = datetime.now(timezone.utc)
    reasons: list[str] = []
    if KILL_SWITCH.exists():
        reasons.append(f"kill switch {KILL_SWITCH} present")
    if args.remaining_pct is not None and args.remaining_pct < args.min_remaining:
        reasons.append(f"quota headroom {args.remaining_pct:g}% < "
                       f"{args.min_remaining:g}% minimum")
    if reasons:
        print(json.dumps({"ok": False, "held": reasons}))
        return 1

    try:
        report = json.loads(Path(args.input).read_text(encoding="utf-8"))
        specs = report.get("accepted") or []
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"bad input: {exc}"[:300]}))
        return 2

    state = load_state()
    seen = recent_keys(state, now)
    launched_today = len(state.get("launched", []))
    cap_left = max(0, args.max_per_day - launched_today)
    if cap_left == 0:
        print(json.dumps({"ok": False, "held": [
            f"daily cap {args.max_per_day} reached ({launched_today} launched in 24h)"],
            "launched_today": launched_today}))
        return 1
    effective_limit = min(args.limit, cap_left)
    chosen = []
    for spec in specs:
        if len(chosen) >= effective_limit:
            break
        if spec.get("lane") != "devin_cloud" or spec.get("task_class") != "repo_work":
            continue
        if spec.get("repo") not in ("chaba", "ada-voice", "sunsynk-card",
                                    "mddb-fork", "gods-eye-view"):
            continue
        if (spec.get("task_id") in seen or spec.get("source_hash") in seen):
            continue
        chosen.append(spec)

    if not args.live:
        print(json.dumps({
            "ok": True, "dry_run": True, "would_launch": len(chosen),
            "mode": args.mode, "launched_24h": launched_today,
            "daily_cap": args.max_per_day, "cap_left": cap_left,
            "tasks": [{"task_id": s["task_id"], "card_ref": s.get("card_ref"),
                       "repo": s["repo"],
                       "prompt_head": s["prompt"][:160]} for s in chosen],
            "note": "no session created, no quota spent; pass --live to launch",
        }, indent=2))
        return 0

    launched = []
    for spec in chosen:
        payload = build_payload(spec, args.mode)
        try:
            d = api("POST", f"/v3/organizations/{org_id()}/sessions", payload)
        except urllib.error.HTTPError as e:
            print(json.dumps({"ok": False, "task_id": spec["task_id"],
                              "http": e.code, "detail": e.read().decode()[:300]}))
            return 3
        record = {"task_id": spec["task_id"], "source_hash": spec.get("source_hash"),
                  "card_ref": spec.get("card_ref"), "session_id": d.get("session_id"),
                  "url": d.get("url"), "mode": args.mode, "at": now.isoformat()}
        state.setdefault("launched", []).append(record)
        launched.append(record)
        print(json.dumps({"ok": True, "launched": launched}, indent=2))
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
