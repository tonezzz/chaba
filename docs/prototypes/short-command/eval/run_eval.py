#!/usr/bin/env python3
"""Evaluate the tiered recognizer against corpus.jsonl.

Expectation classes in corpus.jsonl:
  "<intent>"    hard command — must be claimed at T0/T1 with that intent
  "t2:<intent>" soft command — real command beyond T0/T1 reach; correct
                outcomes are claim-with-that-intent OR escalate (T2/T3
                territory). Claimed with a DIFFERENT intent = wrong-fire.
  "pass"        non-command — any claim is a wrong-fire.

Metrics (the wrong-fire gate comes first):
  wrong_fires  claimed with wrong intent, or a pass item claimed — 0
  deflection   % of command items (hard + soft) claimed at T0/T1
  misses       hard commands that escalated instead of being claimed
  zones        T1 accept/gray/reject/veto distribution on escalations

Usage:
  python3 run_eval.py                 # full report
  python3 run_eval.py --json          # machine-readable rows
  python3 run_eval.py --sweep         # accept-threshold sweep table
  python3 run_eval.py --accept 0.45 --gray 0.30 --margin 0.06
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from recognizer import Recognizer, load_corpus  # noqa: E402

CORPUS = Path(__file__).resolve().parent.parent / "corpus.jsonl"


def evaluate(rec: Recognizer, corpus: list[dict]) -> dict:
    rows = []
    wrong_fires, deflected, commands, passes = [], 0, 0, 0
    tier_counts = Counter()
    zone_counts = Counter()
    confs = []

    for item in corpus:
        expect = item["expect"]
        if expect == "pass":
            want, soft = None, False
        elif expect.startswith("t2:"):
            want, soft = expect[3:], True
        else:
            want, soft = expect, False

        r = rec.recognize(item["text"])
        got = r["intent"]
        if want is None:
            passes += 1
        else:
            commands += 1
        if r["tier"] != "T3":
            tier_counts[r["tier"]] += 1
            confs.append(r["confidence"])
        if r.get("zone"):
            zone_counts[r["zone"]] += 1
        if got is not None and got == want:
            deflected += 1 if want is not None else 0

        if got is not None and got != want:
            # claimed a pass item, or claimed a command with the
            # wrong intent — both are wrong-fires
            wrong_fires.append({"text": item["text"], "expect": expect,
                                "got": got, "tier": r["tier"],
                                "confidence": round(r["confidence"], 3)})
            ok = False
        elif want is not None and got is None and not soft:
            ok = False  # hard command escalated — a miss
        else:
            ok = True   # correct claim, correct pass, or soft escalate

        rows.append({"text": item["text"], "lang": item.get("lang"),
                     "expect": expect, "tier": r["tier"],
                     "zone": r.get("zone"),
                     "intent": got, "confidence": round(r["confidence"], 3),
                     "ok": ok})

    misses = [r for r in rows
              if not r["ok"] and r["expect"] != "pass"
              and not r["expect"].startswith("t2:")
              and r["intent"] is None]
    soft_escalated = [r for r in rows
                      if r["expect"].startswith("t2:")
                      and r["intent"] is None]
    return {
        "n": len(corpus),
        "commands": commands,
        "pass_items": passes,
        "wrong_fires": len(wrong_fires),
        "wrong_fire_items": wrong_fires,
        "deflection_pct": round(100 * deflected / commands, 1)
        if commands else None,
        "missed_commands": len(misses),
        "soft_escalated_to_t2": len(soft_escalated),
        "tier_counts": dict(tier_counts),
        "zone_counts": dict(zone_counts),
        "rows": rows,
        "_miss_rows": misses,
        "_soft_rows": soft_escalated,
    }


def _recognizer(args) -> Recognizer:
    kw = {}
    for attr, param in (("accept", "accept"), ("gray", "gray"),
                        ("margin", "margin")):
        v = getattr(args, attr, None)
        if v is not None:
            kw[param] = v
    return Recognizer(**kw)


def cmd_report(rec: Recognizer, corpus: list[dict]) -> int:
    s = evaluate(rec, corpus)
    rows, misses = s["rows"], s["_miss_rows"]
    soft = s["_soft_rows"]
    print(f"corpus: {s['n']} items ({s['commands']} commands, "
          f"{s['pass_items']} pass-through)")
    print(f"wrong-fires: {s['wrong_fires']}  (gate: must be 0)"
          + ("  <-- FAIL" if s["wrong_fires"] else "  OK"))
    print(f"deflection: {s['deflection_pct']}%   "
          f"missed hard commands: {s['missed_commands']}   "
          f"soft->T2/T3: {s['soft_escalated_to_t2']}")
    print(f"tiers: {s['tier_counts']}   zones: {s['zone_counts']}")
    if misses:
        print("\nmissed commands:")
        for m in misses:
            print(f"  [{m['tier']}] {m['text']!r} expected={m['expect']}")
    if soft:
        print("\nsoft commands that escalated (expected — T2's job):")
        for m in soft:
            print(f"  {m['text']!r} expected={m['expect']}")
    if s["wrong_fire_items"]:
        print("\nWRONG-FIRES:")
        for w in s["wrong_fire_items"]:
            print(f"  [{w['tier']} {w['confidence']}] {w['text']!r} "
                  f"claimed={w['got']} expected={w['expect']}")
    fails = [r for r in rows if not r["ok"]]
    if fails:
        print(f"\nall failures ({len(fails)}):")
        for f in fails:
            print(f"  {f['text']!r}: expect={f['expect']} "
                  f"got={f['intent']}@{f['tier']}")
    return 1 if s["wrong_fires"] or s["missed_commands"] else 0


def cmd_sweep(corpus: list[dict], margin: float) -> int:
    """Sweep the T1 accept threshold; gray = accept - 0.15 band.

    Prints the precision/recall frontier: the lowest accept threshold
    with zero wrong-fires is the recommended operating point.
    """
    print(f"{'accept':>6} {'gray':>6} {'wrong':>5} {'defl%':>6} "
          f"{'miss':>5} {'t1claims':>8}")
    best = None
    for i in range(30, 76, 2):
        accept = i / 100.0
        gray = max(0.05, accept - 0.15)
        rec = Recognizer(accept=accept, gray=gray, margin=margin)
        s = evaluate(rec, corpus)
        t1 = s["tier_counts"].get("T1", 0)
        print(f"{accept:>6.2f} {gray:>6.2f} {s['wrong_fires']:>5} "
              f"{s['deflection_pct']:>6} {s['missed_commands']:>5} "
              f"{t1:>8}")
        if s["wrong_fires"] == 0 and s["missed_commands"] == 0:
            if best is None or accept < best:
                best = accept
    print(f"\nrecommended accept threshold (lowest with 0 wrong-fire, "
          f"0 miss): {best if best is not None else 'NONE — widen corpus'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sweep", action="store_true",
                    help="accept-threshold sweep (OPS-0919 calibration)")
    ap.add_argument("--accept", type=float, default=None)
    ap.add_argument("--gray", type=float, default=None)
    ap.add_argument("--margin", type=float, default=None)
    ap.add_argument("--corpus", default=str(CORPUS))
    args = ap.parse_args()

    corpus = load_corpus(Path(args.corpus))
    margin = args.margin if args.margin is not None else 0.06

    if args.sweep:
        return cmd_sweep(corpus, margin)

    rec = _recognizer(args)
    if args.json:
        s = evaluate(rec, corpus)
        out = {k: v for k, v in s.items() if not k.startswith("_")}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 1 if s["wrong_fires"] or s["missed_commands"] else 0
    return cmd_report(rec, corpus)


if __name__ == "__main__":
    raise SystemExit(main())
