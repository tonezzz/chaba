#!/usr/bin/env python3
"""Deterministic validator for Devin-cloud handoff proposal specs.

The proposer may suggest work; only this validator may pass a spec onward.
There is no LLM in the loop. It rejects wholesale or emits a bounded set of
accepted specs to stdout / --out — it never writes to a queue or inbox, and
never launches a Devin session. Broker staging is the next increment.

Mirrors scripts/devnest/kk_mac_plan_validator.py, with one extra guard that
matters for board-sourced work: every spec's source_hash is recomputed against
the LIVE card. A card edited after the proposal was made is stale and is
rejected, so a proposal cannot outlive the evidence it was built from.

Usage::

    python3 scripts/devnest/devin_handoff_proposer.py --out /tmp/proposals.json
    python3 scripts/devnest/devin_handoff_validator.py --input /tmp/proposals.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts" / "board"))

_proposer = importlib.import_module("devin_handoff_proposer")
_board_cli = importlib.import_module("board-cli")

SELF_REFERENCE = re.compile(
    r"\b(enqueue|replan|schedule)\b[^.\n]{0,60}\b(task|job|queue|inbox|plan)\b"
    r"|\b(create|spawn|generate)\b[^.\n]{0,60}\b(task|queue|inbox|planner)\b",
    re.I,
)
ALLOWED_CLASS = "repo_work"
ALLOWED_LANE = "devin_cloud"
MIN_PROMPT = 80
MAX_PROMPT = 6000
MAX_ACCEPTED = 2
KILL_SWITCH = _proposer.KILL_SWITCH


def _reject(spec: dict, reasons: list[str]) -> dict:
    return {"task_id": spec.get("task_id") or spec.get("card_ref") or "?",
            "card_ref": spec.get("card_ref"),
            "reasons": reasons}


def recompute_hash(card: dict) -> str:
    return hashlib.sha256(
        f"{card.get('id')}|{card.get('updated')}|{card.get('spec') or ''}"
        .encode("utf-8")
    ).hexdigest()[:12]


def check(spec: dict, args: argparse.Namespace, now: datetime) -> tuple[list[str], dict | None]:
    """Return (reasons, live_card). Empty reasons means accepted."""
    reasons: list[str] = []
    if not isinstance(spec, dict):
        return ["spec must be an object"], None
    if spec.get("lane") != ALLOWED_LANE:
        reasons.append(f"lane must be {ALLOWED_LANE}")
    if spec.get("task_class") != ALLOWED_CLASS:
        reasons.append(f"task_class must be {ALLOWED_CLASS} (depth-1)")
    task_id = str(spec.get("task_id") or "")
    if not _proposer.SLUG.fullmatch(task_id):
        reasons.append("task_id must be a safe slug")
    ref = str(spec.get("card_ref") or "")
    if task_id and ref and task_id != _proposer.slug(ref):
        reasons.append("task_id does not match card_ref")
    if spec.get("repo") not in _proposer.ALLOWED_REPOS:
        reasons.append("repo not in allowlist")

    prompt = str(spec.get("prompt") or "")
    if not MIN_PROMPT <= len(prompt) <= MAX_PROMPT:
        reasons.append("prompt length out of bounds")
    if "/handoff" not in prompt or "Done when:" not in prompt:
        reasons.append("prompt lacks handoff prefix or done-condition")
    if "fresh worktree" not in prompt:
        reasons.append("prompt lacks worktree guardrail")
    if _proposer.has_secret(prompt):
        reasons.append("secret pattern in prompt")
    if SELF_REFERENCE.search(prompt):
        reasons.append("queue/task self-reference — depth-1 violation")
    if _proposer.RISK_MARKER.search(prompt) and not args.allow_risk:
        reasons.append("risk keyword in prompt — human gate")
    if _proposer.DECISION_MARKER.search(prompt):
        reasons.append("decision-shaped prompt — needs Tony")
    if _proposer.HOST_BOUND.search(prompt):
        reasons.append("host-bound prompt (journal/ssh) — no cloud access")
    if _proposer.HUMAN_MARKER.search(prompt):
        reasons.append("human-owned marker in prompt")

    for field in ("expect", "artifact", "timeout", "fallback"):
        if not str(spec.get(field) or "").strip():
            reasons.append(f"missing {field}")

    if KILL_SWITCH.exists():
        reasons.append(f"kill switch {KILL_SWITCH} present")

    if args.remaining_pct is not None and args.remaining_pct < args.min_remaining:
        reasons.append(f"quota headroom {args.remaining_pct:g}% < "
                       f"{args.min_remaining:g}% minimum")

    # Freshness: the live card must still exist and match the proposal hash.
    live = None
    try:
        out = _board_cli.call(
            "GET", f"/cards?id={spec.get('card_id')}&limit=1", None,
            args.ssh or None)
        cards = out.get("cards") or []
        if not cards:
            reasons.append("source card not found on board")
        else:
            live = cards[0]
            if recompute_hash(live) != spec.get("source_hash"):
                reasons.append("source_hash stale — card changed after proposal")
            for r in live.get("requests") or []:
                if r.get("status") not in ("answered", "closed"):
                    reasons.append(f"open request appeared: {r.get('id', '?')}")
            act = live.get("action")
            act = act if isinstance(act, dict) else {}
            if act.get("status") in ("claimed", "running", "queued"):
                reasons.append(f"card now {act['status']} — already owned")
            if act.get("type") == "manual" and not args.allow_manual:
                reasons.append("action.type=manual on live card")
    except Exception as exc:
        reasons.append(f"board read failed: {type(exc).__name__} — fail closed")

    return reasons, live


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="-", help="proposal JSON file, or - for stdin")
    ap.add_argument("--out", default=None, help="write accepted-spec JSON here")
    ap.add_argument("--ssh", default="idc03", help="board-api host")
    ap.add_argument("--remaining-pct", type=float, default=None)
    ap.add_argument("--min-remaining", type=float, default=30.0)
    ap.add_argument("--limit", type=int, default=MAX_ACCEPTED)
    ap.add_argument("--allow-manual", action="store_true")
    ap.add_argument("--allow-risk", action="store_true")
    args = ap.parse_args()

    try:
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(
            encoding="utf-8")
        report = json.loads(raw)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"cannot read proposal: {exc}"[:300]}))
        return 2

    proposals = report.get("candidates") or []
    now = datetime.now(timezone.utc)
    accepted: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for spec in proposals:
        reasons, live = check(spec, args, now)
        if reasons:
            rejected.append(_reject(spec, reasons))
            continue
        key = str(spec.get("source_hash") or spec.get("task_id"))
        if key in seen:
            rejected.append(_reject(spec, ["duplicate source/task id — dedupe"]))
            continue
        if len(accepted) >= args.limit:
            rejected.append(_reject(
                spec, [f"accepted limit {args.limit} reached — rerun with --limit"]))
            continue
        seen.add(key)
        clean = dict(spec)
        clean["validated_at"] = now.isoformat()
        clean["source_verified"] = True
        clean["live_updated"] = (live or {}).get("updated")
        clean["next"] = "broker staging (lane devin_cloud) — not yet implemented"
        accepted.append(clean)

    out = {
        "ok": True,
        "validated_at": now.isoformat(),
        "deterministic": True,
        "mode": "validate_only — no queue write, no Devin session, no quota spent",
        "quota": {"remaining_pct": args.remaining_pct,
                  "min_required_pct": args.min_remaining},
        "counts": {"input": len(proposals), "accepted": len(accepted),
                   "rejected": len(rejected)},
        "accepted": accepted,
        "rejected": rejected,
    }
    payload = json.dumps(out, ensure_ascii=False, indent=2)
    print(payload)
    if args.out:
        Path(args.out).expanduser().write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
