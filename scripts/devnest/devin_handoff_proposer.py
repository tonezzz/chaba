#!/usr/bin/env python3
"""Dry-run candidate generator for Devin-cloud handoffs.

This is a PROPOSER, not a queue writer and not a launcher. It reads the board
through the canonical board-api, applies the DevNest cloud-handoff gates, and
emits normalized candidate specs for a human to review. It never creates a
Devin session, never spends quota, and never mutates a card.

Flow (design record: docs/kb/devnest-capacity-aware-dispatch-procedure.md)::

    board-api /cards
        -> safe-candidate ranking (card-pick policy)
        -> cloud-handoff gates (this file)
        -> candidate spec artifact (stdout / --out)
        -> deterministic validator (later)
        -> devnest_capacity_broker lane devin_cloud (later)
        -> Devin v3 API create session (later)

Guardrails inherited from ssot.devin-autonomy.yml and the DevNest procedure:
no synthetic work, t4/R3/R4 never, no secrets, quiet hours, kill switch, and
a visible reason on every hold (gate visibility rule).

Usage::

    python3 scripts/devnest/devin_handoff_proposer.py --limit 2
    python3 scripts/devnest/devin_handoff_proposer.py --remaining-pct 22 --json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts" / "board"))

_board_cli = importlib.import_module("board-cli")
_card_pick = importlib.import_module("card-pick")

# Repo allowlist mirrors ssot.devnest-lanes.yml (dispatch runners whitelist).
ALLOWED_REPOS = (
    "chaba", "ada-voice", "sunsynk-card", "mddb-fork", "gods-eye-view",
)
KILL_SWITCH = Path("/tmp/no-devin-cloud-handoff")
QUIET_HOURS = (0, 6)  # ICT, inclusive start / exclusive end

MIN_TEXT_CHARS = 80
MAX_PROMPT_CHARS = 6000
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
HUMAN_MARKER = re.compile(
    r"\b(human[- ]owned|not for dispatch|do not dispatch|manual[- ]only|"
    r"needs? tony|tony decision|not safe to auto)\b", re.I,
)
# Hard risks only: mutating/host/spend actions. Plain mentions such as
# "deploy-ada.sh" or "no secrets" are not why a card is held.
RISK_MARKER = re.compile(
    r"\b(production|prod writes?|dns|rotate|rekey|purchase|payment|"
    r"paid call|spend|destructive|delete prod|rm -rf)\b"
    r"|\bdeploy\b[^.\n]{0,80}\b(idc\d+|prod|tony-|mn01|con01|web root)\b",
    re.I,
)
DECISION_MARKER = re.compile(
    r"\b(sso|access boundary|confirm intent|decision needed|needs? a decision|"
    r"policy decision|should we|where (should|does) the credential|"
    r"supervised|human[ _-]?watch|human_minutes|live human|decide s\d)\b", re.I,
)
# A cloud VM has no SSH access to our hosts. Cards whose spec requires
# journalctl/systemctl/ssh on a named host belong to a host lane, not cloud.
HOST_BOUND = re.compile(
    r"\b(journalctl|systemctl|ssh\s|on host|target host|timer-alert|curl)\b"
    r"|\bhost\s*:"
    r"|\b(idc0[123]|tony-(omen|dell|macbook)|con01|mn01|ada-dev|kk-mac)\b",
    re.I,
)
RECOVERABILITY_BAD = re.compile(r"\bR[34]\b")

try:  # reuse the validator's secret patterns rather than duplicating them
    _validator = importlib.import_module("kk_mac_plan_validator")
    SECRET_PATTERNS = _validator.SECRET_PATTERNS
except Exception:  # pragma: no cover - fallback keeps this script standalone
    SECRET_PATTERNS = [
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
        re.compile(
            r"\b(api[_-]?key|secret|token|password|credential)\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9_\-./+]{8,}", re.I),
        re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{10,}", re.I),
    ]


def _act(card: dict) -> dict:
    a = card.get("action")
    return a if isinstance(a, dict) else {}


def _text(card: dict) -> str:
    return "\n".join(str(card.get(k) or "") for k in
                     ("title", "brief", "spec")).strip()


def has_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")[:60]
    return s if SLUG.fullmatch(s) else ""


def repo_of(card: dict, default: str) -> tuple[str | None, str]:
    """Resolve (repo, source). Never guess between two named repos."""
    action = _act(card)
    named = str(action.get("repo") or "").strip().lower()
    if named in ALLOWED_REPOS:
        return named, "action.repo"
    text = _text(card)
    hits = [r for r in ALLOWED_REPOS if re.search(rf"\b{re.escape(r)}\b", text, re.I)]
    if len(hits) == 1:
        return hits[0], "card text"
    if len(hits) > 1:
        return None, f"ambiguous: {','.join(hits)}"
    return (default, "operator default") if default in ALLOWED_REPOS else (None, "no default")


def waiting_verdict(card_id: str) -> dict | None:
    """Advisory only: record the strict runner gate, but do not gate on it.

    The runner gate requires host/artifact/verifier fields; a cloud handoff
    carries its done-condition in the prompt instead, so a HOLD here is not
    disqualifying. It is recorded for transparency on the report.
    """
    script = REPO / "scripts" / "board" / "waiting_cards.py"
    try:
        p = subprocess.run(
            [sys.executable, str(script), "--evaluate", card_id, "--json"],
            capture_output=True, text=True, timeout=25,
        )
        if p.returncode == 0:
            data = json.loads(p.stdout)
            return {"eligible": data.get("eligible"),
                    "reasons": data.get("reasons") or []}
    except Exception as exc:
        return {"error": type(exc).__name__}
    return None


def gate(card: dict, args: argparse.Namespace, now: datetime) -> tuple[bool, str, dict]:
    """Return (propose?, visible reason, metadata). Every hold names its gate."""
    act = _act(card)
    meta: dict = {}
    col = str(card.get("column") or "")
    if col in ("done", "archive", "review"):
        return False, f"column={col} — not an open work card", meta
    status = str(act.get("status") or "")
    if status in ("claimed", "running", "queued"):
        return False, f"action.status={status} — already owned", meta
    open_requests = [r for r in (card.get("requests") or [])
                     if r.get("status") not in ("answered", "closed")]
    if open_requests:
        return False, f"open request {open_requests[0].get('id', '?')}", meta

    autonomy = str(card.get("autonomy") or act.get("autonomy") or "t1").lower()
    meta["autonomy"] = autonomy
    if autonomy in ("t3", "t4"):
        return False, f"autonomy={autonomy} — needs human approval", meta
    if act.get("type") == "manual" and not args.allow_manual:
        return False, "action.type=manual — human-owned unless --allow-manual", meta

    text = _text(card)
    if len(text) < MIN_TEXT_CHARS:
        return False, "thin brief/spec — not self-contained", meta
    if HUMAN_MARKER.search(text):
        return False, "human-owned marker in brief/spec", meta
    if DECISION_MARKER.search(text):
        return False, "decision-shaped card — needs Tony, not a handoff", meta
    if HOST_BOUND.search(text) or str(card.get("id") or "").startswith("timer-alert-"):
        return False, "host-bound work (journal/ssh) — no cloud access", meta
    if has_secret(text):
        return False, "secret pattern in card text", meta
    risks = sorted({m.group(0).lower() for m in RISK_MARKER.finditer(text)})
    meta["risk_flags"] = risks
    if risks and not args.allow_risk:
        return False, "risk keywords " + ",".join(risks) + " — human gate", meta
    blob = text + " " + json.dumps(act, ensure_ascii=False)
    rec = RECOVERABILITY_BAD.search(blob)
    if rec:
        return False, f"recoverability {rec.group(1)} — never autonomous", meta

    repo, repo_source = repo_of(card, args.default_repo)
    if not repo:
        return False, f"repo unresolved ({repo_source}) — cannot route a handoff", meta
    meta["repo"] = repo
    meta["repo_source"] = repo_source

    if KILL_SWITCH.exists():
        return False, f"kill switch {KILL_SWITCH} present", meta
    if args.remaining_pct is not None and args.remaining_pct < args.min_remaining:
        return False, (f"quota headroom {args.remaining_pct:g}% < "
                       f"{args.min_remaining:g}% minimum"), meta

    hour = now.hour
    in_quiet = QUIET_HOURS[0] <= hour < QUIET_HOURS[1]
    meta["quiet_hours"] = in_quiet
    meta["devin_mode"] = args.model
    return True, "eligible" + (" (quiet hours — live run would hold)" if in_quiet else ""), meta


def build_spec(card: dict, why: str, meta: dict, verdict: dict | None) -> dict:
    ref = str(card.get("ref") or card.get("id") or "")
    task_id = slug(ref) or slug(str(card.get("id") or "")) or "card"
    text = _text(card)
    brief = str(card.get("brief") or card.get("title") or "").strip()
    spec = str(card.get("spec") or "").strip()
    body = (f"Card {ref or card.get('id')}: {card.get('title', '')}\n\n"
            f"{brief}\n\n{spec}\n").strip()
    prompt = (
        f"/handoff {body[:MAX_PROMPT_CHARS]}\n\n"
        f"Guardrails: work in a fresh worktree; never edit the live checkout; "
        f"no secrets in chat or commits; no host mutations; PR only via "
        f"scripts/git-safe-push.sh.\n"
        f"Done when: the card's stated done-condition is met, checks are green, "
        f"and a PR is open with a short verification note. Stop at the PR."
    )
    source_hash = hashlib.sha256(
        f"{card.get('id')}|{card.get('updated')}|{spec}".encode("utf-8")
    ).hexdigest()[:12]
    return {
        "task_id": task_id,
        "task_class": "repo_work",
        "lane": "devin_cloud",
        "repo": meta["repo"],
        "repo_source": meta.get("repo_source"),
        "devin_mode": meta.get("devin_mode", "swe-2-medium"),
        "card_ref": ref,
        "card_id": card.get("id"),
        "source_hash": source_hash,
        "score_why": why,
        "autonomy": meta.get("autonomy"),
        "risk_flags": meta.get("risk_flags", []),
        "quiet_hours": meta.get("quiet_hours", False),
        "waiting_verdict": verdict,
        "prompt": prompt,
        "expect": "tests green + PR open, no host mutations",
        "artifact": f"dispatch-outcome-{task_id}.md + PR",
        "timeout": "45m",
        "fallback": "manual",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=2,
                    help="max candidate specs (default 2)")
    ap.add_argument("--scan", type=int, default=20,
                    help="how many ranked cards to evaluate (default 20)")
    ap.add_argument("--ssh", default="idc03",
                    help="host running board-api ('' = local BOARD_API)")
    ap.add_argument("--api", default=None)
    ap.add_argument("--remaining-pct", type=float, default=None,
                    help="daily Devin allowance remaining, percent; unknown omitted")
    ap.add_argument("--min-remaining", type=float, default=30.0,
                    help="minimum headroom to propose (default 30)")
    # Cloud API accepts normal/fast/fusion/lite/ultra/fast-ultra only;
    # swe-2-* are CLI/Desktop modes and are rejected by the v3 API.
    ap.add_argument("--model", default="lite",
                    help="devin_mode for candidate sessions (API-valid: lite)")
    ap.add_argument("--default-repo", default="chaba",
                    help="repo when a card does not name one (default chaba)")
    ap.add_argument("--allow-manual", action="store_true",
                    help="override the action.type=manual hold (review carefully)")
    ap.add_argument("--allow-risk", action="store_true",
                    help="override the risk-keyword hold (review carefully)")
    ap.add_argument("--out", default=None, help="write JSON report here")
    ap.add_argument("--markdown", action="store_true",
                    help="also print a short human-readable summary to stderr")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    try:
        cards = _card_pick.fetch_cards(args.ssh or None, args.api)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:300]}))
        return 2

    ranked = _card_pick.pick(cards, "high-value", 7, now)
    candidates: list[dict] = []
    held: list[dict] = []
    seen: set[str] = set()

    for card, why in ranked[: args.scan]:
        ok, reason, meta = gate(card, args, now)
        if not ok:
            held.append({"ref": card.get("ref") or card.get("id"),
                         "id": card.get("id"), "reason": reason})
            continue
        if len(candidates) >= args.limit:
            held.append({"ref": card.get("ref") or card.get("id"),
                         "id": card.get("id"),
                         "reason": f"candidate limit {args.limit} reached — "
                                   "rerun with a larger --limit to include"})
            continue
        spec = build_spec(card, why, meta, waiting_verdict(str(card.get("id"))))
        if spec["source_hash"] in seen:
            held.append({"ref": spec["card_ref"], "id": spec["card_id"],
                         "reason": "duplicate source hash — dedupe"})
            continue
        seen.add(spec["source_hash"])
        spec["gate_reason"] = reason
        candidates.append(spec)

    report = {
        "ok": True,
        "dry_run": True,
        "mode": "propose_only — no board mutation, no Devin session, no quota spent",
        "generated_at": now.isoformat(),
        "counts": {"scanned": min(len(ranked), args.scan),
                   "proposed": len(candidates), "held": len(held)},
        "quota": {
            "remaining_pct": args.remaining_pct,
            "min_required_pct": args.min_remaining,
            "source": "operator-supplied; meter must be read at app.devin.ai/settings/usage",
        },
        "kill_switch": str(KILL_SWITCH) if KILL_SWITCH.exists() else None,
        "candidates": candidates,
        "held": held,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.out:
        Path(args.out).expanduser().write_text(payload + "\n", encoding="utf-8")
    if args.markdown:
        lines = [f"Dry-run: {len(candidates)} candidate(s), {len(held)} held."]
        for c in candidates:
            lines.append(f"- {c['card_ref']} [{c['repo']}/{c['devin_mode']}] "
                         f"{c['task_id']} — {c['score_why']}")
        for h in held[:10]:
            lines.append(f"  held {h['ref']}: {h['reason']}")
        print("\n".join(lines), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
