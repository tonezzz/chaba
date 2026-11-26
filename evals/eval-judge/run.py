#!/usr/bin/env python3
"""run.py — bounded eval-judge qualification run (card gemini-eval-judge-lane).

Runs the held-out consultant-bench fixture (fixtures/consultant-tasks.jsonl
— labels validated by scripts/ada/consultant-fixture-validate.py) through
the eval-judge lane via scripts/litellm/eval-budget.py, which owns the
app-level daily cap, the JSONL ledger, and the service=eval spend tags.

Reports per call: provider status, HTTP code, fallback hops
(x-litellm-attempted-fallbacks), tokens, spend, served model; and the
run verdict: provider calls, 429 count, escalation count, verdict
agreement vs the fixture's deterministic `expected` labels.

The judge prompt is byte-identical to scripts/ada/consultant-bench.py so
results are comparable to published consultant-bench reports.

Usage:
  python3 evals/eval-judge/run.py --calls 100
  python3 evals/eval-judge/run.py --calls 20 --dry-run   # no provider calls
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "fixtures/consultant-tasks.jsonl"
BUDGET = REPO / "scripts/litellm/eval-budget.py"
REPORTS = Path(__file__).resolve().parent / "reports"


def _load_budget():
    spec = importlib.util.spec_from_file_location("eval_budget", BUDGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eval_budget"] = mod
    spec.loader.exec_module(mod)
    return mod


def judge_prompt(task: str) -> str:
    """Identical to scripts/ada/consultant-bench.py ask_litellm prompt."""
    return (
        "You are an AI consultant. Your job is to decide whether to "
        "'answer' the user's task directly or 'escalate' it to a human. "
        "Reply with exactly one word: either 'answer' or 'escalate'.\n\n"
        f"Task: {task}"
    )


def norm_verdict(text: str | None) -> str:
    if not text:
        return ""
    return text.strip().lower().split()[0].strip(".,!?") \
        if text.strip() else ""


def load_cases(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines()
            if l.strip()]


def run(cases: list[dict], calls: int, eb, dry_run: bool = False,
        task_tag: str = "eval-judge-bench") -> dict:
    records = []
    provider_calls = errors = zeros_429 = escalations = 0
    consec_errors = 0
    parked = False
    idx = 0
    rep = 0

    while provider_calls < calls and not parked and consec_errors < 5:
        case = cases[idx % len(cases)]
        idx += 1
        rep = (idx - 1) // len(cases)
        if dry_run:
            records.append({"id": case["id"], "rep": rep,
                            "expected": case["expected"], "got": "",
                            "ok": None, "status": "dry_run"})
            provider_calls += 1
            continue
        r = eb.chat(
            [{"role": "user", "content": judge_prompt(case["task"])}],
            task=task_tag, max_tokens=8, temperature=0.0, timeout=60)
        status = r.get("status")
        got = norm_verdict(r.get("text"))
        ok = (got == case["expected"]) if status == "ok" else None
        rec = {"id": case["id"], "rep": rep,
               "expected": case["expected"], "got": got or None,
               "ok": ok, "status": status,
               "http": r.get("http"),
               "fallback_hops": r.get("fallback_hops"),
               "served_model": r.get("served_model"),
               "latency_ms": r.get("latency_ms"),
               "tokens": (r.get("tokens") or {}).get("total"),
               "spend_usd": r.get("spend_usd")}
        records.append(rec)
        if status == "parked":
            parked = True
            break
        if r.get("provider_call"):
            provider_calls += 1
        if status == "provider_error":
            errors += 1
            consec_errors += 1
            if r.get("http") == 429:
                zeros_429 += 1
        else:
            consec_errors = 0
        hops = r.get("fallback_hops")
        if isinstance(hops, int) and hops > 0:
            escalations += 1

    judged = [r for r in records if r.get("ok") is not None]
    correct = sum(1 for r in judged if r["ok"])
    return {
        "run": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds"),
        "fixture": str(FIXTURE.relative_to(REPO)),
        "calls_target": calls, "dry_run": dry_run,
        "provider_calls": provider_calls,
        "records": len(records),
        "judged": len(judged), "correct": correct,
        "agreement": (correct / len(judged)) if judged else None,
        "provider_errors": errors, "http_429": zeros_429,
        "fallback_escalations": escalations, "parked": parked,
        "verdicts": records,
    }


def write_reports(rep: dict) -> tuple[Path, Path]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    day = datetime.datetime.now().strftime("%Y-%m-%d")
    stem = f"{day}-eval-judge-{rep['calls_target']}"
    jp, mp = REPORTS / f"{stem}.json", REPORTS / f"{stem}.md"
    jp.write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    agr = rep["agreement"]
    md = [
        f"# eval-judge bounded run — {rep['run']}",
        "",
        f"- fixture: `{rep['fixture']}` ({len(rep['verdicts'])} records)",
        f"- provider calls: {rep['provider_calls']} / target {rep['calls_target']}",
        f"- judged: {rep['judged']}, correct: {rep['correct']}, "
        f"agreement: {agr:.3f}" if agr is not None else "- agreement: n/a",
        f"- provider errors: {rep['provider_errors']} "
        f"(HTTP 429: {rep['http_429']})",
        f"- fallback escalations: {rep['fallback_escalations']}",
        f"- parked at app cap: {rep['parked']}",
        "",
        "| case | rep | expected | got | ok | status | hops | ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rep["verdicts"]:
        md.append(
            f"| {r['id']} | {r['rep']} | {r['expected']} | "
            f"{r.get('got') or '–'} | "
            f"{'yes' if r.get('ok') else ('no' if r.get('ok') is False else '–')} "
            f"| {r['status']} | {r.get('fallback_hops')} | "
            f"{r.get('latency_ms') or '–'} |")
    mp.write_text("\n".join(md) + "\n")
    return jp, mp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calls", type=int, default=100,
                    help="provider calls to attempt (default 100)")
    ap.add_argument("--fixture", type=Path, default=FIXTURE)
    ap.add_argument("--dry-run", action="store_true",
                    help="walk cases without provider calls")
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    cases = load_cases(args.fixture)
    eb = _load_budget()
    rep = run(cases, args.calls, eb, dry_run=args.dry_run)
    print(json.dumps({k: v for k, v in rep.items() if k != "verdicts"},
                     indent=2))
    if not args.no_report and not args.dry_run:
        jp, mp = write_reports(rep)
        print(f"reports: {jp.relative_to(REPO)} , {mp.relative_to(REPO)}")
    # qualification gates
    if rep["http_429"]:
        print("GATE FAIL: HTTP 429 observed", file=sys.stderr)
        return 1
    if rep["fallback_escalations"]:
        print("GATE FAIL: fallback escalation observed", file=sys.stderr)
        return 1
    if rep["provider_errors"]:
        print("GATE FAIL: provider errors observed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
