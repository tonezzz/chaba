#!/usr/bin/env python3
"""Grade the diverse-negative third gate run for gemini-decision-1.

No API calls, no secrets. Reads the dataset and the one batched Decisions
response; reports the default 0.5 threshold, the two previously calibrated
thresholds, per-negative-family false approvals, and the confident-NO shortcut.
"""
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

RESULTS = Path(__file__).resolve().parent / "results"
ds = json.load(open(RESULTS / "g4-decision-gate-diverse60-dataset.json"))
resp = json.load(open(RESULTS / "g4-decision-gate-diverse60-response.json"))
assert len(ds["items"]) == len(resp["answers"]) == 60

rows = []
for it in ds["items"]:
    a = resp["answers"][f"ready_{it['n']}"]
    rows.append({
        "n": it["n"], "id": it["id"], "brief": it["brief"], "label": it["label"],
        "kind": it["kind"], "label_reason": it["label_reason"],
        "p_yes": a["noul"], "confidence": a.get("confidence", max(a["noul"], 1 - a["noul"])),
    })

THRESHOLDS = {"default": 0.5, "train_calibrated": 0.5161926625710843,
              "holdout_zero_fp": 0.536574}


def confusion(pred, labels):
    tp = sum(1 for p, l in zip(pred, labels) if l and p)
    fn = sum(1 for p, l in zip(pred, labels) if l and not p)
    tn = sum(1 for p, l in zip(pred, labels) if not l and not p)
    fp = sum(1 for p, l in zip(pred, labels) if not l and p)
    n = len(labels)
    return {"tp": tp, "fn": fn, "tn": tn, "fp": fp, "n": n,
            "accuracy": round((tp + tn) / n, 4),
            "approve_precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "approve_recall": round(tp / (tp + fn), 4) if tp + fn else None}


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"low": round(max(0, c - h), 4), "high": round(min(1, c + h), 4)}


def zero_fp_threshold():
    best = None
    for t in sorted({r["p_yes"] for r in rows} | {0.0, 1.0}):
        c = confusion([r["p_yes"] >= t for r in rows], [r["label"] for r in rows])
        if c["fp"] == 0 and c["tp"] > 0:
            if best is None or c["tp"] > best[1]["tp"] or (c["tp"] == best[1]["tp"] and t > best[0]):
                best = (t, c)
    return {"threshold": round(best[0], 6), "confusion": best[1]} if best else None


labels = [r["label"] for r in rows]
neg = [r for r in rows if not r["label"]]
pos = [r for r in rows if r["label"]]
arms = {}
for name, t in THRESHOLDS.items():
    c = confusion([r["p_yes"] >= t for r in rows], labels)
    arms[name] = {"threshold": t, "confusion": c,
                  "false_approval_rate_wilson95": wilson(c["fp"], len(neg))}

by_family = {}
for fam in sorted({r["kind"] for r in neg}):
    famrows = [r for r in neg if r["kind"] == fam]
    flabels = [r["label"] for r in famrows]
    by_family[fam] = {
        "n": len(famrows),
        "false_approvals_at_0.5": [r["id"] for r in famrows if r["p_yes"] >= 0.5],
        "false_approvals_at_0.536574": [r["id"] for r in famrows if r["p_yes"] >= 0.536574],
        "mean_p_yes": round(mean(r["p_yes"] for r in famrows), 4),
        "max_p_yes": round(max(r["p_yes"] for r in famrows), 4),
    }

high_conf = [r for r in rows if r["confidence"] >= 0.90]

# Sensitivity read only: six NOT_READY briefs are actually arguable dispatch
# requests when judged from the brief alone (a failing test, a dead credential,
# a smoke E2E, an audit finding with a named lever). The primary labels stay
# unchanged; this shows how much of the false-approval gap is label ambiguity.
ARGUABLE = {
    "kk-mac-script-smoke", "cast-loop-breaker-test-failure", "keywatch-or-idc03",
    "keywatch-or-tony-dell", "keywatch-or-tony-omen", "devin-taskdir-gc-dispatch-hosts",
}
generous_labels = [True if r["id"] in ARGUABLE else r["label"] for r in rows]
generous = {
    name: {"threshold": t, "confusion": confusion([r["p_yes"] >= t for r in rows], generous_labels)}
    for name, t in THRESHOLDS.items()
}

out = {
    "schema": "decision-gate-diverse60-graded",
    "date": "2026-11-27",
    "dataset": {
        "counts": ds["counts"], "negative_families": ds["negative_families"],
        "label_rule": ds["label_rule"],
        "disjoint_from": ["60-brief train", "41-brief probe", "110-brief holdout",
                          "130-brief validation"],
    },
    "decisions_api": {
        "model": "gemini-decision-1", "usage": resp.get("usage"),
        "brier": round(mean((r["p_yes"] - (1 if r["label"] else 0)) ** 2
                            for r in rows), 4),
        "thresholds": arms,
        "zero_fp_threshold_on_diverse60": zero_fp_threshold(),
        "mean_p_yes_ready": round(mean(r["p_yes"] for r in pos), 4),
        "mean_p_yes_not_ready": round(mean(r["p_yes"] for r in neg), 4),
        "false_approvals_at_0.5": [
            {"n": r["n"], "id": r["id"], "family": r["kind"],
             "p_yes": round(r["p_yes"], 4), "brief": r["brief"][:220]}
            for r in neg if r["p_yes"] >= 0.5],
        "false_rejects_at_0.5": [
            {"n": r["n"], "id": r["id"], "p_yes": round(r["p_yes"], 4),
             "brief": r["brief"][:220]}
            for r in pos if r["p_yes"] < 0.5],
        "high_confidence_reject_gate": {
            "threshold": 0.90, "n": len(high_conf),
            "all_not_ready": all(not r["label"] for r in high_conf),
            "false_rejects": [r["id"] for r in high_conf if r["label"]],
            "coverage_of_not_ready": f"{sum(1 for r in neg if r['confidence'] >= 0.90)}/40",
        },
        "directional_confident_no": {
            "rule": "reject when p_yes <= 0.10 and confidence >= 0.90",
            "n": sum(1 for r in rows if r["p_yes"] <= 0.10 and r["confidence"] >= 0.90),
            "ids": [r["id"] for r in rows if r["p_yes"] <= 0.10 and r["confidence"] >= 0.90],
            "false_rejects": [r["id"] for r in rows
                              if r["label"] and r["p_yes"] <= 0.10 and r["confidence"] >= 0.90],
            "coverage_of_not_ready": f"{sum(1 for r in neg if r['p_yes'] <= 0.10 and r['confidence'] >= 0.90)}/40",
        },
    },
    "label_ambiguity_sensitivity": {
        "description": "Primary labels unchanged. Sensitivity only: reclassify six briefs a human could reasonably call dispatchable (smoke E2E, failing test, three dead-credential alerts, one audit finding with a named lever) as READY.",
        "reclassified_ids": sorted(ARGUABLE),
        "confusions": generous,
    },
    "negative_family_breakdown": by_family,
    "rows": rows,
}
json.dump(out, open(RESULTS / "g4-decision-gate-diverse60-graded.json", "w"), indent=2)
for name, arm in arms.items():
    print(name, arm["confusion"], "wilson", arm["false_approval_rate_wilson95"])
print("brier", out["decisions_api"]["brier"])
print("zero-FP", out["decisions_api"]["zero_fp_threshold_on_diverse60"])
print("high-conf", out["decisions_api"]["high_confidence_reject_gate"])
for fam, v in by_family.items():
    print("family", fam, v)
