#!/usr/bin/env python3
"""Ada bank-recall drift report — parses ada-ha service journals for recall
hit/miss lines and emits a chaba-events entry when quality drifts.

ada-pi logs:
  bank recall '<bank>': N hit(s), scores=[0.71, ...]      -> hit
  bank recall '<bank>': miss (top scores=[...])           -> miss (escalated)

A rising miss rate or falling hit score means the embedding model, the
threshold, or the data drifted — the events feed surfaces it instead of
silently degrading recall.

Usage:
  recall-drift-report.py                  # analyze last 7 days, print report
  recall-drift-report.py --emit           # also post a chaba-event if drifting
  recall-drift-report.py --since '24 hours' --units ada-ha-tony
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from statistics import mean

DEFAULT_UNITS = ["ada-ha-tony.service", "ada-ha-michael.service"]
# Drift tripwires (fractions of recalls in the window).
MISS_RATE_ALERT = 0.5       # more than half of recalls missed the bank
MIN_SAMPLE = 10             # don't alert on tiny windows
HIT_SCORE_FLOOR = 0.55      # mean hit score below this = embedding drift smell

HIT_RE = re.compile(r"bank recall '([^']+)': (\d+) hit\(s\), scores=\[([^\]]*)\]")
MISS_RE = re.compile(r"bank recall '([^']+)': miss")

EVENT_CMD = [
    "ssh", "tony-dell",
    "python3", "/home/tony/.config/home-assistant/scripts/chaba-event-log.py", "add",
]


def journal_lines(units: list[str], since: str) -> str:
    cmd = ["journalctl", "--user", "--since", since, "-o", "short-iso"]
    for u in units:
        cmd += ["-u", u]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def analyze(text: str) -> dict:
    hits = misses = 0
    scores: list[float] = []
    miss_scores: list[float] = []
    banks: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        if m := HIT_RE.search(line):
            hits += 1
            scores += [float(s) for s in m.group(3).split(",") if s.strip()]
            banks.setdefault(m.group(1), {"hit": 0, "miss": 0})["hit"] += 1
        elif m := MISS_RE.search(line):
            misses += 1
            banks.setdefault(m.group(1), {"hit": 0, "miss": 0})["miss"] += 1
    total = hits + misses
    return {
        "recalls": total,
        "hits": hits,
        "misses": misses,
        "miss_rate": round(misses / total, 3) if total else None,
        "mean_hit_score": round(mean(scores), 3) if scores else None,
        "banks": banks,
    }


def drift_reasons(r: dict) -> list[str]:
    reasons = []
    if r["recalls"] < MIN_SAMPLE:
        return []  # too little signal to judge
    if r["miss_rate"] is not None and r["miss_rate"] > MISS_RATE_ALERT:
        reasons.append(f"miss rate {r['miss_rate']:.0%} > {MISS_RATE_ALERT:.0%}")
    if r["mean_hit_score"] is not None and r["mean_hit_score"] < HIT_SCORE_FLOOR:
        reasons.append(f"mean hit score {r['mean_hit_score']} < {HIT_SCORE_FLOOR}")
    return reasons


def emit_event(report: dict, reasons: list[str], since: str) -> None:
    body = (f"{report['misses']}/{report['recalls']} bank recalls missed the MDDB "
            f"tier in the last {since} ({'; '.join(reasons)}). "
            f"Mean hit score: {report['mean_hit_score']}. "
            "Possible embedding-model drift or threshold miscalibration.")
    payload = json.dumps({
        "title": "Ada memory recall drift",
        "category": "ada-memory",
        "severity": "warn",
        "body": body,
        "requires_response": False,
        "confidence": 0.7,
    })
    try:
        r = subprocess.run(EVENT_CMD + [payload], capture_output=True, text=True, timeout=30)
        print("event emitted" if r.returncode == 0 else f"event emit failed: {r.stderr.strip()}")
    except Exception as exc:
        print(f"event emit failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="7 days ago")
    ap.add_argument("--units", nargs="+", default=DEFAULT_UNITS)
    ap.add_argument("--emit", action="store_true",
                    help="post a chaba-event when drift tripwires fire")
    args = ap.parse_args()

    report = analyze(journal_lines(args.units, args.since))
    print(json.dumps(report, indent=1))
    reasons = drift_reasons(report)
    if reasons:
        print("DRIFT:", "; ".join(reasons))
        if args.emit:
            emit_event(report, reasons, args.since)
        return 1
    print("no drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
