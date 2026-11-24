#!/usr/bin/env python3
"""Validate a KK-Mac planner artifact before it can create new tasks.

The planner is allowed to suggest work; only this deterministic validator may
write candidate specs to the shared DevNest inbox. Design record:
docs/ssot/jobs/devnest/2026-11-24-jevnest-bounded-package-planner.yml
(card jevnest-bounded-package-planner / OPS-1027).

Artifact path:

    real evidence -> planner package on KK-Mac (depth 1, read-only lane)
    -> out/result.json {verified, parsed.candidates[<=3]}
    -> THIS validator on tony-dell (deterministic, no LLM)
    -> normal devnest_capacity_broker staging into devnest/inbox

KK-Mac never writes to any queue; it emits a candidate-spec artifact that
this validator either rejects wholesale or fans out (max 3) through the
normal broker. Planner-generated planner tasks are structurally impossible:
no admitted task_class produces another planner artifact, and prompts that
try to create/enqueue tasks are rejected.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Mirrors kk_mac_llm.ALLOWED_TASKS — operator_brief/safe_route held
# pending re-eval (card kk-mac-admitted-classes-narrow). The class
# allowlist is also the depth-1 guard: no planner class is admitted, so a
# validated candidate can never itself be a planner task.
ALLOWED = {"summary", "structured_extract"}
ALLOWED_LANE = "kk_mac_local"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
FORBIDDEN = re.compile(
    r"\b(package_plan|planner|credential|secret|publish|delete|shell)\b", re.I
)
# Planner self-reference / queue-mutation phrasing. Structural depth-1 is
# enforced by ALLOWED; this catches prompts that try to bootstrap more
# planner work or write to a queue inside an admitted read-only class.
SELF_REFERENCE = re.compile(
    r"\b(create|spawn|generate|enqueue|dispatch|schedule|replan|fan.?out)\b"
    r"[^.\n]{0,60}\b(task|package|job|plan|planner|queue|inbox)\b",
    re.I,
)
# Credential/secret material must never ride a candidate prompt. Matches
# assignments and well-known token prefixes; deliberately not a generic
# high-entropy scan (prompts legitimately contain hashes and ids).
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(
        r"\b(api[_-]?key|apikey|secret|token|password|passwd|credential)"
        r"\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+]{8,}",
        re.I,
    ),
    re.compile(r"\b(sk|pk|ghp|gho|github_pat|xox[baprs]|AKIA|AIza)"
               r"[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{10,}", re.I),
]
DEFAULT_REMOTE = "gdrive:ada-nest/devnest"
# Planner artifacts are only accepted from the KK lane pack root — an
# artifact found anywhere else is not a planner output.
PACK_ROOT_PREFIX = "gdrive:ada-nest/kk-llm/packs/"
MAX_CANDIDATES = 3
MIN_PROMPT_CHARS = 20
MAX_PROMPT_CHARS = 6000
MAX_EVIDENCE_CHARS = 20000
MAX_QUOTES = 3
MAX_QUOTE_CHARS = 300
MAX_FACTS = 3
MAX_FACT_CHARS = 160


def rclone(*args: str, input_text: str | None = None) -> str:
    p = subprocess.run(
        ["rclone", *args], input=input_text, text=True,
        capture_output=True, timeout=60,
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[:300] or "rclone failed")
    return p.stdout


def _has_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def _check_candidate(candidate: dict, i: int, source_id: str,
                     evidence: str, inbox_names: frozenset) -> dict:
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object")
    task_class = candidate.get("task_class")
    lane = candidate.get("lane", ALLOWED_LANE)
    prompt = str(candidate.get("prompt", "")).strip()
    if task_class not in ALLOWED:
        raise ValueError(f"candidate {i}: task class not admitted")
    if lane != ALLOWED_LANE:
        raise ValueError(f"candidate {i}: lane must be {ALLOWED_LANE}")
    if not MIN_PROMPT_CHARS <= len(prompt) <= MAX_PROMPT_CHARS:
        raise ValueError(f"candidate {i}: prompt bounds violated")
    if FORBIDDEN.search(prompt) or FORBIDDEN.search(str(task_class)):
        raise ValueError(f"candidate {i}: forbidden planner/action text")
    if SELF_REFERENCE.search(prompt):
        raise ValueError(f"candidate {i}: planner self-reference")
    if _has_secret(prompt):
        raise ValueError(f"candidate {i}: secret pattern in prompt")
    # Source evidence: every candidate must cite 1..3 literal quotes that
    # appear verbatim (case-insensitive) in the planner's input evidence.
    quotes = candidate.get("evidence_quotes")
    if (
        not isinstance(quotes, list)
        or not 1 <= len(quotes) <= MAX_QUOTES
        or any(
            not isinstance(q, str)
            or not q.strip()
            or len(q) > MAX_QUOTE_CHARS
            or q.lower() not in evidence.lower()
            for q in quotes
        )
    ):
        raise ValueError(f"candidate {i}: evidence quote not in source")
    # Fact bounds: expect.facts is optional but, when present, must be
    # 1..3 short literal-echo tokens (kkmac held-classes lesson — the
    # verifier substring-checks the model's raw response).
    expect = candidate.get("expect") or {}
    if not isinstance(expect, dict):
        raise ValueError(f"candidate {i}: expect must be an object")
    facts = expect.get("facts")
    staged_expect: dict = {}
    if facts is not None:
        if (
            not isinstance(facts, list)
            or not 1 <= len(facts) <= MAX_FACTS
            or any(
                not isinstance(f, str) or not f.strip()
                or len(f) > MAX_FACT_CHARS
                for f in facts
            )
        ):
            raise ValueError(f"candidate {i}: expect.facts bounds violated")
        staged_expect["facts"] = [f.strip() for f in facts]
    task_id = f"{source_id}-followup-{i}"
    if not SLUG.fullmatch(task_id):
        raise ValueError("candidate task ID unsafe")
    if task_id in inbox_names:
        raise ValueError(f"candidate {i}: task_id already in inbox")
    return {
        "task_id": task_id,
        "lane": ALLOWED_LANE,
        "task_class": task_class,
        "model": "qwen2.5:32b",
        "prompt": prompt,
        "expect": staged_expect,
        "source_id": source_id,
        "planner_validated": True,
    }


def validate_artifact(
    task: dict,
    result: dict,
    *,
    inbox_names: frozenset = frozenset(),
) -> list[dict]:
    """Pure validation of a planner pack's task.json + result.json.

    Raises ValueError on the first violated check; returns the staged
    candidate specs (max MAX_CANDIDATES) on success. Offline fixture mode
    calls this directly; the remote path goes through validate().
    """
    if result.get("verified") is not True:
        raise ValueError("planner artifact is not independently verified")
    parsed = result.get("parsed")
    source_id = str(task.get("source_id") or "")
    if not SLUG.fullmatch(source_id):
        raise ValueError("source_id missing or unsafe")
    if not isinstance(parsed, dict) or parsed.get("source_id") != source_id:
        raise ValueError("source_id mismatch")
    evidence = task.get("evidence")
    if (
        not isinstance(evidence, str)
        or not evidence.strip()
        or len(evidence) > MAX_EVIDENCE_CHARS
    ):
        raise ValueError("source evidence missing or unbounded")
    if _has_secret(evidence):
        raise ValueError("source evidence contains a secret pattern")
    candidates = parsed.get("candidates")
    if (
        not isinstance(candidates, list)
        or not 1 <= len(candidates) <= MAX_CANDIDATES
    ):
        raise ValueError("candidate count must be 1..3")
    return [
        _check_candidate(c, i, source_id, evidence, inbox_names)
        for i, c in enumerate(candidates, 1)
    ]


def validate(pack: str, remote: str = DEFAULT_REMOTE,
             *, inbox_names: frozenset = frozenset()) -> list[dict]:
    """Remote path: fetch the pack's task/result, enforce the artifact
    root, then run the same checks as validate_artifact."""
    if not pack.startswith(PACK_ROOT_PREFIX):
        raise ValueError("pack is outside the planner artifact root")
    task = json.loads(rclone("cat", f"{pack}/inputs/task.json"))
    result = json.loads(rclone("cat", f"{pack}/out/result.json"))
    return validate_artifact(task, result, inbox_names=inbox_names)


def remote_inbox_names(remote: str) -> frozenset:
    names = set()
    for line in rclone("lsf", f"{remote}/inbox", "--files-only").splitlines():
        name = line.strip()
        if name.endswith(".json"):
            names.add(name[: -len(".json")])
    return frozenset(names)


def ledger(remote: str, record: dict) -> None:
    """Append-only per-run metrics record for the planner-vs-feed
    comparison (see job doc). One small object per run; a later
    aggregator folds them into the lift/wait/cost/reject/loop report."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rclone(
        "rcat", f"{remote}/planner/ledger/{ts}.json",
        input_text=json.dumps(record) + "\n",
    )


def _load_fixture(fixture: Path) -> tuple[dict, dict, frozenset]:
    task = json.loads((fixture / "task.json").read_text())
    result = json.loads((fixture / "result.json").read_text())
    inbox_file = fixture / "inbox.txt"
    names = frozenset(
        line.strip() for line in inbox_file.read_text().splitlines()
        if line.strip()
    ) if inbox_file.exists() else frozenset()
    return task, result, names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", nargs="?", help="planner pack dir "
                    f"(must start {PACK_ROOT_PREFIX})")
    ap.add_argument("--remote", default=DEFAULT_REMOTE)
    ap.add_argument("--fixture", type=Path,
                    help="offline held-out fixture dir "
                         "(task.json + result.json [+ inbox.txt]); "
                         "validates only, never writes")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate a remote pack and record the ledger "
                         "entry but do NOT stage candidates into the "
                         "inbox — the held-out/shadow phase gate")
    args = ap.parse_args()
    try:
        if args.fixture:
            task, result, names = _load_fixture(args.fixture)
            candidates = validate_artifact(task, result, inbox_names=names)
            print(json.dumps({"validated": len(candidates),
                              "fixture": str(args.fixture)}))
            return 0
        if not args.pack:
            ap.error("pack or --fixture is required")
        names = remote_inbox_names(args.remote)
        candidates = validate(args.pack, args.remote, inbox_names=names)
        if args.dry_run:
            ledger(args.remote, {
                "at": datetime.now(timezone.utc).isoformat(),
                "pack": args.pack,
                "validated": len(candidates),
                "task_ids": [c["task_id"] for c in candidates],
                "dry_run": True,
            })
            print(json.dumps({"validated": len(candidates),
                              "dry_run": True}))
            return 0
        for spec in candidates:
            rclone(
                "rcat", f"{args.remote}/inbox/{spec['task_id']}.json",
                input_text=json.dumps(spec) + "\n",
            )
        ledger(args.remote, {
            "at": datetime.now(timezone.utc).isoformat(),
            "pack": args.pack,
            "validated": len(candidates),
            "task_ids": [c["task_id"] for c in candidates],
        })
        print(json.dumps({"validated": len(candidates)}))
        return 0
    except (RuntimeError, ValueError, json.JSONDecodeError,
            OSError) as exc:
        if args.pack and not args.fixture:
            try:
                ledger(args.remote, {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "pack": args.pack,
                    "validated": 0,
                    "error": str(exc)[:300],
                    "dry_run": bool(args.dry_run),
                })
            except Exception:
                pass
        print(json.dumps({"validated": 0, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
