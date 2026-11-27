#!/usr/bin/env python3
"""Grade the independent 130-brief validation run for the decision-1 gate.

Primary arm: gemini-decision-1 noul answers. The optional full-model arm is
only used when a complete generateContent response is present; a blocked arm
is recorded explicitly rather than silently dropped.

No API calls; no secrets.
"""
import json
import math
from pathlib import Path
from statistics import mean

RESULTS = Path(__file__).resolve().parent / "results"
DS = RESULTS / "g4-decision-gate-validation130-dataset.json"
D1 = RESULTS / "g4-decision-gate-validation130-response.json"
FM = RESULTS / "g4-decision-gate-validation130-fullmodel-response.json"
OUT = RESULTS / "g4-decision-gate-validation130-graded.json"
THRESHOLDS = {"default": 0.5, "train_calibrated": 0.5161926625710843,
              "holdout_zero_fp": 0.536574}

ds = json.load(open(DS))
d1 = json.load(open(D1))
rows = []
for it in ds["items"]:
    a = d1["answers"][f"ready_{it['n']}"]
    rows.append({
        "n": it["n"], "id": it["id"], "label": it["label"], "source": it["source"],
        "kind": it.get("kind"), "brief": it["brief"],
        "p_yes": a["noul"],
        "confidence": a.get("confidence", max(a["noul"], 1 - a["noul"])),
    })

fm_present = False
fm_by_n = {}
if FM.exists():
    fm = json.load(open(FM))
    if "candidates" in fm and fm["candidates"][0].get("finishReason") == "STOP":
        try:
            fm_rows = json.loads(fm["candidates"][0]["content"]["parts"][0]["text"])
            if len(fm_rows) == len(rows) and {r["n"] for r in fm_rows} == {r["n"] for r in rows}:
                fm_by_n = {r["n"]: r for r in fm_rows}
                fm_present = True
                for r in rows:
                    f = fm_by_n[r["n"]]
                    r["fm_ready"] = bool(f["ready"])
                    r["fm_p_yes"] = float(f["p_yes"])
        except (ValueError, KeyError, IndexError):
            pass


def confusion(pred, labels):
    tp = sum(1 for p, l in zip(pred, labels) if l and p)
    fn = sum(1 for p, l in zip(pred, labels) if l and not p)
    tn = sum(1 for p, l in zip(pred, labels) if not l and not p)
    fp = sum(1 for p, l in zip(pred, labels) if not l and p)
    return {"tp": tp, "fn": fn, "tn": tn, "fp": fp, "n": len(labels),
            "accuracy": round((tp + tn) / len(labels), 4),
            "approve_precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "approve_recall": round(tp / (tp + fn), 4) if tp + fn else None}


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"low": round(max(0, c - h), 4), "high": round(min(1, c + h), 4)}


def brier(scores, labels):
    return round(mean((s - (1 if l else 0)) ** 2 for s, l in zip(scores, labels)), 4)


def zero_fp_threshold(rows, key, labels):
    best = None
    for t in sorted({r[key] for r in rows} | {0.0, 1.0}):
        c = confusion([r[key] >= t for r in rows], labels)
        if c["fp"] == 0 and c["tp"] > 0:
            if best is None or c["tp"] > best[1]["tp"] or (c["tp"] == best[1]["tp"] and t > best[0]):
                best = (t, c)
    return {"threshold": round(best[0], 6), "confusion": best[1]} if best else None


labels = [r["label"] for r in rows]
pos = [r for r in rows if r["label"]]
neg = [r for r in rows if not r["label"]]
high_conf = [r for r in rows if r["confidence"] >= 0.90]
d1_arms = {}
for name, t in THRESHOLDS.items():
    c = confusion([r["p_yes"] >= t for r in rows], labels)
    d1_arms[name] = {"threshold": t, "confusion": c,
                     "false_approval_rate_wilson95": wilson(c["fp"], len(neg))}

# Label audit: the deterministic marker matcher put two genuinely dispatchable
# cards in the NOT_READY pool. Both carry a spec and are in the done column, so
# the marker matched an in-sentence qualifier rather than a deferral:
#   n=37 "not yet in our SSOT"  -> describes the surfaces, not the action
#   n=111 "only after policy checks" -> an ordering constraint inside a task
# Report the as-built labels as primary and a corrected-label sensitivity read.
LABEL_CORRECTIONS = {"gemini-dev-capabilities-research-2026-11-26",
                    "opencode-safe-storage-cleanup-report"}
def sensitivity(corrected_labels):
    return {name: confusion([r["p_yes"] >= t for r in rows], corrected_labels)
            for name, t in THRESHOLDS.items()}

corrected_labels = [True if r["id"] in LABEL_CORRECTIONS else r["label"] for r in rows]
high_conf_corrected = [r for r in rows if r["confidence"] >= 0.90]

out = {
    "schema": "decision-gate-validation-130-graded",
    "date": "2026-11-27",
    "dataset": {
        "counts": ds["counts"], "negative_mix": ds["negative_mix"],
        "disjoint_from": ["60-brief train set", "41-brief earlier probe", "110-brief holdout"],
    },
    "decisions_api": {
        "model": "gemini-decision-1",
        "usage": d1.get("usage"),
        "brier": brier([r["p_yes"] for r in rows], labels),
        "thresholds": d1_arms,
        "zero_fp_threshold_on_validation": zero_fp_threshold(rows, "p_yes", labels),
        "mean_p_yes_ready": round(mean(r["p_yes"] for r in pos), 4),
        "mean_p_yes_not_ready": round(mean(r["p_yes"] for r in neg), 4),
        "high_confidence_reject_gate": {
            "threshold": 0.90, "n": len(high_conf),
            "all_not_ready": all(not r["label"] for r in high_conf),
            "coverage_of_not_ready": f"{sum(1 for r in neg if r['confidence'] >= 0.90)}/{len(neg)}",
            "false_rejects": [r["id"] for r in high_conf if r["label"]],
        },
    },
    "label_audit": {
        "as_built": "Primary results keep the deterministic marker labels unchanged; no retroactive tuning.",
        "marker_misfires": [
            {"n": 37, "id": "gemini-dev-capabilities-research-2026-11-26",
             "marker": "not yet", "note": "'not yet in our SSOT' qualifies the surfaces, not the action; spec present, card was dispatched"},
            {"n": 111, "id": "opencode-safe-storage-cleanup-report",
             "marker": "only after", "note": "'only after policy checks' is an in-task ordering constraint; spec present, card was dispatched"},
        ],
        "negative_pool_skew": "65/70 negatives are the 'read the note/check the note/details in the note' template family, so the set is hard on deferral-to-note but thin on other negative types.",
        "corrected_label_sensitivity": sensitivity(corrected_labels),
        "corrected_zero_fp_threshold": zero_fp_threshold(
            [dict(r, p_yes=r["p_yes"]) for r in rows], "p_yes", corrected_labels),
        "corrected_high_confidence_reject": {
            "n": len(high_conf_corrected),
            "false_rejects": [r["id"] for i, r in enumerate(rows)
                              if r["confidence"] >= 0.90 and corrected_labels[i]],
        },
    },
    "full_model_generative": {
        "status": "completed" if fm_present else "blocked",
        "block_reason": None if fm_present else
        "gemini-3.8-flash returned 503 high demand on 3 attempts; alternate free models returned 503/429/404",
    },
    "comparison_to_prior_holdout": {
        "prior_holdout_at_0.5162": {"tp": 37, "fn": 18, "tn": 54, "fp": 1,
                                    "false_approval_wilson95": {"low": 0.0032, "high": 0.0961}},
        "prior_zero_fp_threshold": 0.536574,
        "validation_at_0.5162": d1_arms["train_calibrated"]["confusion"],
        "validation_at_0.536574": d1_arms["holdout_zero_fp"]["confusion"],
    },
    "rows": rows,
}
json.dump(out, open(OUT, "w"), indent=2)
for name, arm in d1_arms.items():
    print(name, arm["confusion"], "wilson", arm["false_approval_rate_wilson95"])
print("brier", out["decisions_api"]["brier"])
print("zero-FP", out["decisions_api"]["zero_fp_threshold_on_validation"])
print("high-conf", out["decisions_api"]["high_confidence_reject_gate"])
print("full model", out["full_model_generative"])
