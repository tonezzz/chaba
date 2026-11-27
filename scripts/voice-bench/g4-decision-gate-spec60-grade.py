#!/usr/bin/env python3
"""Grade the fresh brief+spec Decisions arm against fixed thresholds only.

No API calls, no secrets, no threshold tuning. Zero-FP sweep is reported as
exploratory and explicitly inadmissible for adoption on this same set.
"""
import json
import math
from pathlib import Path
from statistics import mean

RESULTS = Path(__file__).resolve().parent / "results"
ds = json.load(open(RESULTS / "g4-decision-gate-spec60-dataset.json"))
resp = json.load(open(RESULTS / "g4-decision-gate-spec60-response.json"))
answers = resp["answers"]
assert len(ds["items"]) == len(answers) == 60

rows = []
for it in ds["items"]:
    n = it["n"]
    a = answers[f"ready_{n}"]
    rows.append({"n": n, "id": it["id"], "label": it["label"], "kind": it["kind"],
                 "label_reason": it["label_reason"], "p_yes": a["noul"],
                 "confidence": a.get("confidence")})

THRESHOLDS = {"default": 0.5, "train_calibrated": 0.5161926625710843,
              "holdout_zero_fp": 0.536574}
labels = [r["label"] for r in rows]
neg_n = sum(1 for l in labels if not l)


def confusion(pred, labs):
    tp = sum(1 for p, l in zip(pred, labs) if l and p)
    fn = sum(1 for p, l in zip(pred, labs) if l and not p)
    tn = sum(1 for p, l in zip(pred, labs) if not l and not p)
    fp = sum(1 for p, l in zip(pred, labs) if not l and p)
    return {"tp": tp, "fn": fn, "tn": tn, "fp": fp, "n": len(labs),
            "accuracy": round((tp + tn) / len(labs), 4),
            "approve_precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "approve_recall": round(tp / (tp + fn), 4) if tp + fn else None}


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"low": round(max(0, c - h), 4), "high": round(min(1, c + h), 4)}


arms = {}
for name, t in THRESHOLDS.items():
    c = confusion([r["p_yes"] >= t for r in rows], labels)
    arms[name] = {"threshold": t, "confusion": c,
                  "false_approval_rate_wilson95": wilson(c["fp"], neg_n)}

# Exploratory only: tuned on this set, so inadmissible as evidence for adoption.
zero_fp = None
for t in sorted({r["p_yes"] for r in rows} | {0.0, 1.0}):
    c = confusion([r["p_yes"] >= t for r in rows], labels)
    if c["fp"] == 0 and c["tp"] > 0:
        if zero_fp is None or c["tp"] > zero_fp["confusion"]["tp"]:
            zero_fp = {"threshold": round(t, 6), "confusion": c}

by_family = {}
for fam in sorted({r["kind"] for r in rows if not r["label"]}):
    fr = [r for r in rows if not r["label"] and r["kind"] == fam]
    by_family[fam] = {
        "n": len(fr), "mean_p_yes": round(mean(r["p_yes"] for r in fr), 4),
        "false_approvals_at_0.5": [r["id"] for r in fr if r["p_yes"] >= 0.5],
        "false_approvals_at_0.536574": [r["id"] for r in fr if r["p_yes"] >= 0.536574],
    }

shortcuts = {
    "confidence_ge_0.90_reject": {
        "n": sum(1 for r in rows if (r["confidence"] or 0) >= 0.90),
        "false_rejects": [r["id"] for r in rows if r["label"] and (r["confidence"] or 0) >= 0.90],
    },
    "directional_confident_no": {
        "rule": "reject when p_yes <= 0.10 and confidence >= 0.90",
        "ids": [r["id"] for r in rows if r["p_yes"] <= 0.10 and (r["confidence"] or 0) >= 0.90],
        "false_rejects": [r["id"] for r in rows if r["label"] and r["p_yes"] <= 0.10
                          and (r["confidence"] or 0) >= 0.90],
        "coverage_of_not_ready": f"{sum(1 for r in rows if not r['label'] and r['p_yes'] <= 0.10 and (r['confidence'] or 0) >= 0.90)}/{neg_n}",
    },
}

out = {
    "schema": "decision-gate-spec60-graded",
    "date": "2026-11-27",
    "source": "One batched Decisions call over 60 fresh cards with brief+spec; fixed thresholds only",
    "usage": resp.get("usage"),
    "brier": round(mean((r["p_yes"] - (1 if r["label"] else 0)) ** 2 for r in rows), 4),
    "primary_arms": arms,
    "zero_fp_sweep_exploratory_tuned_on_this_set_not_adoptable": zero_fp,
    "negative_family_breakdown": by_family,
    "confident_shortcuts": shortcuts,
    "false_approvals_at_0.5": [r["id"] for r in rows if not r["label"] and r["p_yes"] >= 0.5],
    "false_rejects_at_0.5": [r["id"] for r in rows if r["label"] and r["p_yes"] < 0.5],
    "rows": rows,
}
json.dump(out, open(RESULTS / "g4-decision-gate-spec60-graded.json", "w"), indent=2)
for name, v in arms.items():
    print(name, v["confusion"], "wilson", v["false_approval_rate_wilson95"])
print("brier", out["brier"])
print("zero_fp_exploratory", zero_fp)
print("families", {k: (v["n"], len(v["false_approvals_at_0.5"])) for k, v in by_family.items()})
print("shortcuts", shortcuts)
