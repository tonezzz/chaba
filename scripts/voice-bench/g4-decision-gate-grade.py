#!/usr/bin/env python3
"""Grade expanded decision-gate run and calibrate approve threshold on held-out labels."""
import json
import random
from statistics import mean

DATASET = "/tmp/opencode/decision-gate-expanded-dataset.json"
RESPONSE = "/tmp/opencode/decision-gate-expanded-response.json"
OUT = "/tmp/opencode/decision-gate-expanded-graded.json"

ds = json.load(open(DATASET))
resp = json.load(open(RESPONSE))
answers = resp["answers"]
items = []
for it in ds["items"]:
    a = answers[f"ready_{it['n']}"]
    items.append({
        "n": it["n"], "id": it["id"], "label": it["label"], "source": it["source"],
        "brief": it["brief"], "p_yes": a["noul"],
        "confidence": a.get("confidence", max(a["noul"], 1 - a["noul"])),
    })


def confusion(rows, threshold=0.5):
    tp = sum(1 for r in rows if r["label"] and r["p_yes"] >= threshold)
    fn = sum(1 for r in rows if r["label"] and r["p_yes"] < threshold)
    tn = sum(1 for r in rows if not r["label"] and r["p_yes"] < threshold)
    fp = sum(1 for r in rows if not r["label"] and r["p_yes"] >= threshold)
    n = len(rows)
    return {
        "tp": tp, "fn": fn, "tn": tn, "fp": fp, "n": n,
        "accuracy": round((tp + tn) / n, 4) if n else None,
        "approve_precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "approve_recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "reject_precision": round(tn / (tn + fn), 4) if tn + fn else None,
    }


def brier(rows):
    return round(mean((r["p_yes"] - (1 if r["label"] else 0)) ** 2 for r in rows), 4)


rng = random.Random(42)
pos = [r for r in items if r["label"]]
neg = [r for r in items if not r["label"]]
rng.shuffle(pos)
rng.shuffle(neg)
train = pos[:20] + neg[:20]
test = pos[20:] + neg[20:]

# Calibrate the most permissive threshold with zero false approvals on train.
candidates = sorted({r["p_yes"] for r in train} | {0.0, 1.0})
chosen = None
for t in candidates:
    c = confusion(train, t)
    if c["fp"] == 0 and c["tp"] > 0:
        if chosen is None or c["tp"] > chosen[1]["tp"] or (c["tp"] == chosen[1]["tp"] and t > chosen[0]):
            chosen = (t, c)
threshold = chosen[0]

high_conf_rejects = [r for r in items if r["confidence"] >= 0.90]
out = {
    "schema": "decision-gate-expanded-graded",
    "date": "2026-11-26",
    "dataset_counts": {"ready": len(pos), "not_ready": len(neg)},
    "usage": resp.get("usage"),
    "overall_at_0.5": confusion(items),
    "brier": brier(items),
    "mean_p_yes_ready": round(mean(r["p_yes"] for r in pos), 4),
    "mean_p_yes_not_ready": round(mean(r["p_yes"] for r in neg), 4),
    "min_p_yes_ready": min(r["p_yes"] for r in pos),
    "max_p_yes_not_ready": max(r["p_yes"] for r in neg),
    "high_confidence_reject_gate": {
        "threshold": 0.90,
        "n": len(high_conf_rejects),
        "all_not_ready": all(not r["label"] for r in high_conf_rejects),
        "coverage_of_not_ready": f"{sum(1 for r in neg if r['confidence'] >= 0.90)}/{len(neg)}",
    },
    "approve_threshold_calibration": {
        "split": "seed 42, stratified 20/20 train and 10/10 test",
        "train_confusion_at_chosen": chosen[1],
        "chosen_threshold": threshold,
        "test_confusion_at_chosen": confusion(test, threshold),
        "test_confusion_at_0.5": confusion(test),
        "full_set_reference_at_chosen": confusion(items, threshold),
    },
    "rows": items,
}
json.dump(out, open(OUT, "w"), indent=2)
print("overall@0.5", out["overall_at_0.5"])
print("brier", out["brier"], "p_yes ranges", out["min_p_yes_ready"], out["max_p_yes_not_ready"])
print("high-conf reject", out["high_confidence_reject_gate"])
print("threshold", threshold)
print("train", chosen[1])
print("test@chosen", out["approve_threshold_calibration"]["test_confusion_at_chosen"])
print("test@0.5", out["approve_threshold_calibration"]["test_confusion_at_0.5"])
