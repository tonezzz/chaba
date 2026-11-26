#!/usr/bin/env python3
"""Eval harness: scores corpus.jsonl against the recognizer, per tier.

    python3 eval/run_eval.py                 # default thresholds
    python3 eval/run_eval.py --sweep         # threshold sweep for T1

Reports accuracy, deflection rate (share of all inputs resolved
locally), wrong-fire rate (commands claimed that were wrong), and
per-tier breakdown. A 'gray' result counts as pass-through (deflected
to provider) — it is not a wrong-fire, and is reported separately.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scr import Recognizer

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus.jsonl")
COMMANDS = os.environ.get(
    "SCR_COMMANDS",
    os.path.join(os.path.dirname(HERE), "commands.json"))


def load(path=CORPUS):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def corpus_arg(argv):
    for i, a in enumerate(argv):
        if a == "--corpus" and i + 1 < len(argv):
            return argv[i + 1]
    return CORPUS


def evaluate(rec, corpus):
    rows, stats = [], {"match": 0, "gray": 0, "no_match": 0}
    correct = wrong = 0
    per_tier = {}
    for item in corpus:
        res = rec.recognize(item["text"])
        exp = item["expect"]
        stats[res["status"]] += 1
        ok = None
        if res["status"] == "match":
            ok = res["intent"] == exp
            correct += ok
            wrong += (not ok)
            per_tier[res["tier"]] = per_tier.get(res["tier"], 0) + 1
        elif exp == "no_match":
            ok = True                       # correctly passed through
            correct += 1
        rows.append({"text": item["text"], "expect": exp,
                     "got": res["intent"], "status": res["status"],
                     "tier": res["tier"], "score": res["score"], "ok": ok})
    n = len(corpus)
    return {
        "n": n,
        "correct": correct,
        "accuracy": round(correct / n, 3),
        "wrong_fire": wrong,
        "wrong_fire_rate": round(wrong / n, 3),
        "gray": stats["gray"],
        "deflection": round((stats["match"] + stats["gray"]) / n, 3),
        "per_tier": per_tier,
        "rows": rows,
    }


def main(argv):
    corpus = load(corpus_arg(argv))
    if "--sweep" in argv:
        for hi, lo in [(0.45, 0.35), (0.5, 0.4), (0.55, 0.45),
                       (0.6, 0.5), (0.65, 0.55)]:
            rec = Recognizer(COMMANDS, accept=hi, gray_lo=lo)
            s = evaluate(rec, corpus)
            print("accept>=%.2f gray>=%.2f | acc=%.3f wrong=%d "
                  "deflect=%.3f gray=%d"
                  % (hi, lo, s["accuracy"], s["wrong_fire"],
                     s["deflection"], s["gray"]))
        return 0
    rec = Recognizer(COMMANDS)
    s = evaluate(rec, corpus)
    print(json.dumps({k: v for k, v in s.items() if k != "rows"},
                     indent=2))
    print("\nfailures:")
    for r in s["rows"]:
        if r["ok"] is False:
            print("  %-52s expect=%-14s got=%s (%s, %s)"
                  % (r["text"], r["expect"], r["got"],
                     r["status"], r["score"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
