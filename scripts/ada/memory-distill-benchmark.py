#!/usr/bin/env python3
"""Benchmark for memory-distill.py extraction quality.

Feeds fixture session summaries (memory-distill-scenarios.yml) through
the real Gemini extraction path — no MDDB reads or writes — and scores:

  recall    = expected items found / total expected
  precision = matched candidates / total candidates

A candidate "hits" an expectation when one candidate's text contains all
of its `contains` substrings (case-insensitive) and matches `bank`/`kind`
when given (kind checked after bank-policy coercion, same as production).

  memory-distill-benchmark.py                 # human report
  memory-distill-benchmark.py --json out.json
  memory-distill-benchmark.py --scenario person-fact
  memory-distill-benchmark.py --dump          # print all raw candidates
Env: GEMINI_API_KEY (required), ADA_SUMMARY_MODEL
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import yaml

_spec = importlib.util.spec_from_file_location(
    "memory_distill", Path(__file__).with_name("memory-distill.py")
)
md = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md)

SCENARIOS = Path(__file__).with_name("memory-distill-scenarios.yml")


def hits(candidate: dict, want: dict) -> bool:
    text = str(candidate.get("text") or "").lower()
    if any(s.lower() not in text for s in want.get("contains") or []):
        return False
    want_banks = want.get("bank")
    if want_banks:
        if isinstance(want_banks, str):
            want_banks = [want_banks]
        if candidate.get("bank") not in want_banks:
            return False
    if want.get("kind") and candidate.get("kind") != want["kind"]:
        return False
    return True


def run_scenario(sc: dict, banks: dict[str, dict], dump: bool) -> dict:
    instance = sc.get("instance") or "tony"
    sessions = [{"key": f"{sc['name']}-{i}", "date": "2026-09-22",
                 "text": t} for i, t in enumerate(sc["sessions"])]
    raw = md.extract_candidates(sessions, banks, instance)
    candidates = []
    for c in raw:
        ok = md.valid_candidate(c, banks, instance)
        if ok:
            candidates.append(ok[0])
    if dump:
        for c in candidates:
            print(f"      raw: {c['bank']}/{c['subject']} [{c['kind']}] "
                  f"{c['text'][:100]!r}")

    expect = sc.get("expect") or []
    found, misses = 0, []
    for w in expect:
        if any(hits(c, w) for c in candidates):
            found += 1
        else:
            misses.append(w)
    extra = max(0, len(candidates) - found)
    max_extra = sc.get("max_extra", 2)
    return {"name": sc["name"], "expected": len(expect), "found": found,
            "extra": extra, "ok_extra": extra <= max_extra,
            "misses": misses, "candidates": len(candidates)}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", help="run only this scenario name")
    ap.add_argument("--min-recall", type=float, default=0.75)
    ap.add_argument("--min-precision", type=float, default=0.5)
    ap.add_argument("--dump", action="store_true",
                    help="print every extracted candidate")
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    scenarios = yaml.safe_load(SCENARIOS.read_text()).get("scenarios") or []
    if args.scenario:
        scenarios = [s for s in scenarios if s["name"] == args.scenario]
        if not scenarios:
            print(f"no scenario named {args.scenario!r}")
            return 2

    banks = md.load_writable_banks()
    results = []
    tot_exp = tot_found = tot_cand = bad_extra = 0
    for sc in scenarios:
        r = run_scenario(sc, banks, args.dump)
        results.append(r)
        tot_exp += r["expected"]
        tot_found += r["found"]
        tot_cand += r["candidates"]
        bad_extra += not r["ok_extra"]
        mark = "PASS" if r["found"] == r["expected"] and r["ok_extra"] \
            else "FAIL"
        print(f"[{mark}] {r['name']}: {r['found']}/{r['expected']} expected, "
              f"{r['extra']} extra candidate(s)")
        for m in r["misses"]:
            print(f"      missed: {m}")

    recall = tot_found / max(1, tot_exp)
    precision = tot_found / max(1, tot_cand)
    print(f"\nrecall {tot_found}/{tot_exp} = {recall:.0%}  "
          f"precision {tot_found}/{tot_cand} = {precision:.0%}  "
          f"extra-cap violations: {bad_extra}")

    report = {"model": md.MODEL, "recall": round(recall, 3),
              "precision": round(precision, 3),
              "expected": tot_exp, "found": tot_found,
              "candidates": tot_cand, "scenarios": results}
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")

    ok = recall >= args.min_recall and precision >= args.min_precision \
        and bad_extra == 0
    print("VERDICT: PASS" if ok else "VERDICT: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
