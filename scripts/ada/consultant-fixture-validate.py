#!/usr/bin/env python3
"""Validate a consultant-bench fixture (fixtures/consultant-tasks.jsonl).

Checks each line parses as JSON, carries the keys consultant-bench.py needs
(id, task, expected), that expected is answer|escalate, ids are unique, and
the set is large/balanced enough to discriminate candidate models.
Exits non-zero on any violation.
"""
import argparse
import json
import sys

EXPECTED = {"answer", "escalate"}
MIN_CASES = 18          # ~20 real cases target; allow some slack
MIN_PER_VERDICT = 6     # enough per class to spot a degenerate always-X model


def validate_fixture(path, min_cases=MIN_CASES, min_per_verdict=MIN_PER_VERDICT):
    errors = []
    seen_ids = set()
    counts = {"answer": 0, "escalate": 0}
    n = 0

    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                case = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"line {lineno}: invalid JSON ({e})")
                continue
            if not isinstance(case, dict):
                errors.append(f"line {lineno}: not a JSON object")
                continue
            for key in ("id", "task", "expected"):
                if key not in case:
                    errors.append(f"line {lineno} ({case.get('id', '?')}): missing '{key}'")
            cid = case.get("id")
            if cid in seen_ids:
                errors.append(f"line {lineno}: duplicate id '{cid}'")
            seen_ids.add(cid)
            if not isinstance(case.get("task"), str) or not case["task"].strip():
                errors.append(f"line {lineno} ({cid}): empty task")
            exp = case.get("expected")
            if exp not in EXPECTED:
                errors.append(f"line {lineno} ({cid}): expected must be one of {sorted(EXPECTED)}, got {exp!r}")
            else:
                counts[exp] += 1

    if n < min_cases:
        errors.append(f"only {n} cases (< {min_cases}) — too few to discriminate models")
    for verdict, c in counts.items():
        if c < min_per_verdict:
            errors.append(f"only {c} '{verdict}' cases (< {min_per_verdict}) — imbalanced")

    return errors, n, counts


def main():
    p = argparse.ArgumentParser(description="Validate consultant-bench fixture jsonl")
    p.add_argument("fixture", nargs="?", default="fixtures/consultant-tasks.jsonl")
    p.add_argument("--min-cases", type=int, default=MIN_CASES)
    p.add_argument("--min-per-verdict", type=int, default=MIN_PER_VERDICT)
    args = p.parse_args()

    errors, n, counts = validate_fixture(args.fixture, args.min_cases, args.min_per_verdict)
    if errors:
        for e in errors:
            print(f"FAIL {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {n} cases (answer={counts['answer']}, escalate={counts['escalate']}) in {args.fixture}")


if __name__ == "__main__":
    main()
