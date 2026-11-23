#!/usr/bin/env python3
"""Append arbiter-labeled rows to ada-voice orch-triage-cases.jsonl.

HELD until Tony finishes the ~100-row spot-check (board answer on
dispatch-triage-arbiter-label-pass, 2026-11-21: "check first, then
append"). Two modes:

  # 1. append the auto-accepted (above-threshold) rows
  python3 append-suite.py --append suite-append-<date>.jsonl \
      --cases ~/CascadeProjects/ada-voice/tests/bench/orch-triage-cases.jsonl

  # 2. after the spot-check, feed adjudications {text, label} — rows are
  #    appended with slice harvest-<date>-checked; a dropped row uses
  #    label "drop" and is skipped
  python3 append-suite.py --review review-queue-<date>.jsonl \
      --adjudications adjudications.jsonl \
      --cases .../orch-triage-cases.jsonl --slice harvest-<date>-checked

Idempotent: texts already present (normalized match) are skipped.
Writes a .bak of the cases file before modifying. Does NOT push or
deploy — the ada-voice checkout commit is a separate, human-gated step.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())


def load_jsonl(path: str) -> list[dict]:
    out = []
    for ln in open(path):
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True,
                    help="path to orch-triage-cases.jsonl")
    ap.add_argument("--append", help="suite-append-<date>.jsonl rows")
    ap.add_argument("--review", help="review-queue-<date>.jsonl rows")
    ap.add_argument("--adjudications",
                    help="jsonl {text,label} decisions for review rows")
    ap.add_argument("--slice", default=None,
                    help="slice override for adjudicated rows")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cases = Path(args.cases)
    existing = {norm(json.loads(ln)["text"])
                for ln in open(cases) if ln.strip()}
    added, skipped = [], 0

    if args.append:
        for r in load_jsonl(args.append):
            if norm(r["text"]) in existing:
                skipped += 1
                continue
            added.append({"text": r["text"], "kind": "triage",
                          "label": r["label"], "set": "triage",
                          "slice": r.get("slice") or "harvest"})

    if args.review and args.adjudications:
        adj = {norm(r["text"]): r for r in load_jsonl(args.adjudications)}
        rev = load_jsonl(args.review)
        missing = 0
        for r in rev:
            n = norm(r["text"])
            if n in existing:
                skipped += 1
                continue
            a = adj.get(n)
            if a is None:
                missing += 1
                continue
            if a.get("label") == "drop":
                continue
            added.append({"text": r["text"], "kind": "triage",
                          "label": a.get("label", r["label"]),
                          "set": "triage",
                          "slice": args.slice or r.get("slice")
                                   or "harvest-checked"})
        if missing:
            print(f"note: {missing} review rows have no adjudication "
                  f"— skipped", file=sys.stderr)

    print(f"would add {len(added)} rows, {skipped} dupes skipped "
          f"({len(existing)} existing)")
    if args.dry_run or not added:
        return
    shutil.copy2(cases, str(cases) + ".bak")
    with open(cases, "a") as f:
        for r in added:
            f.write(json.dumps(r) + "\n")
    print(f"appended {len(added)} -> {cases} (backup: {cases}.bak)")


if __name__ == "__main__":
    main()
