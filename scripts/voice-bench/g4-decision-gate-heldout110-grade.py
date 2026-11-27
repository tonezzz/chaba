#!/usr/bin/env python3
"""Grade the 110-brief held-out comparison: Decisions API gate vs full generative model.

Reads the four captured JSON artifacts from scripts/voice-bench/results/ and
writes g4-decision-gate-heldout110-graded.json. No API calls; no secrets.
"""
import json
import math
from pathlib import Path
from statistics import mean

RESULTS = Path(__file__).resolve().parent / "results"
DS = RESULTS / "g4-decision-gate-heldout110-dataset.json"
D1 = RESULTS / "g4-decision-gate-heldout110-response.json"
FM = RESULTS / "g4-decision-gate-heldout110-fullmodel-response.json"
OUT = RESULTS / "g4-decision-gate-heldout110-graded.json"
CALIBRATED_THRESHOLD = 0.5161926625710843  # from the 60-brief train/calibration split

ds = json.load(open(DS))
d1 = json.load(open(D1))
fm = json.load(open(FM))
fm_rows = json.loads(fm["candidates"][0]["content"]["parts"][0]["text"])
assert len(fm_rows) == 110 and {r["n"] for r in fm_rows} == set(range(1, 111))
fm_by_n = {r["n"]: r for r in fm_rows}

rows = []
for it in ds["items"]:
    n = it["n"]
    a = d1["answers"][f"ready_{n}"]
    f = fm_by_n[n]
    rows.append({
        "n": n, "id": it["id"], "label": it["label"], "source": it["source"],
        "brief": it["brief"],
        "d1_p_yes": a["noul"],
        "d1_confidence": a.get("confidence", max(a["noul"], 1 - a["noul"])),
        "fm_ready": bool(f["ready"]), "fm_p_yes": float(f["p_yes"]),
    })


def confusion(pred, label):
    tp = sum(1 for p, l in zip(pred, label) if l and p)
    fn = sum(1 for p, l in zip(pred, label) if l and not p)
    tn = sum(1 for p, l in zip(pred, label) if not l and not p)
    fp = sum(1 for p, l in zip(pred, label) if not l and p)
    n = len(label)
    return {
        "tp": tp, "fn": fn, "tn": tn, "fp": fp, "n": n,
        "accuracy": round((tp + tn) / n, 4),
        "approve_precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "approve_recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "reject_precision": round(tn / (tn + fn), 4) if tn + fn else None,
    }


def wilson(k, n, z=1.96):
    if n == 0:
        return {"low": None, "high": None}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"low": round(max(0, c - h), 4), "high": round(min(1, c + h), 4)}


def brier(scores, labels):
    return round(mean((s - (1 if l else 0)) ** 2 for s, l in zip(scores, labels)), 4)


def zero_fp_threshold(rows, key):
    """Lowest observed score threshold that approves at least one brief with zero FPs."""
    cands = sorted({r[key] for r in rows} | {0.0, 1.0})
    best = None
    for t in cands:
        c = confusion([r[key] >= t for r in rows], label)
        if c["fp"] == 0 and c["tp"] > 0:
            if best is None or c["tp"] > best[1]["tp"] or (c["tp"] == best[1]["tp"] and t > best[0]):
                best = (t, c)
    return {"threshold": round(best[0], 6), "confusion": best[1],
            "approve_recall": round(best[1]["tp"] / len(pos), 4)} if best else None


label = [r["label"] for r in rows]
pos = [r for r in rows if r["label"]]
neg = [r for r in rows if not r["label"]]
d1_at_05 = [r["d1_p_yes"] >= 0.5 for r in rows]
d1_at_cal = [r["d1_p_yes"] >= CALIBRATED_THRESHOLD for r in rows]
fm_bool = [r["fm_ready"] for r in rows]
fm_at_05 = [r["fm_p_yes"] >= 0.5 for r in rows]
c_d1_cal = confusion(d1_at_cal, label)
c_fm_bool = confusion(fm_bool, label)
high_conf = [r for r in rows if r["d1_confidence"] >= 0.90]
agree = sum(1 for a, b in zip(d1_at_cal, fm_bool) if a == b)

out = {
    "schema": "decision-gate-heldout-110-graded",
    "date": "2026-11-27",
    "dataset": {
        "counts": {"ready": len(pos), "not_ready": len(neg)},
        "disjoint_from": ["60-brief train set", "20-brief calibration holdout", "41-brief earlier probe"],
        "source": ds["source"],
    },
    "arms": {
        "decisions_api": {
            "model": "gemini-decision-1",
            "endpoint": "POST /v1beta/decisions (one batched call, 110 questions)",
            "latency_s": 0.77,
            "usage": d1.get("usage"),
            "confusion_at_0.5": confusion(d1_at_05, label),
            "confusion_at_calibrated_0.5162": c_d1_cal,
            "brier": brier([r["d1_p_yes"] for r in rows], label),
            "mean_p_yes_ready": round(mean(r["d1_p_yes"] for r in pos), 4),
            "mean_p_yes_not_ready": round(mean(r["d1_p_yes"] for r in neg), 4),
            "min_p_yes_ready": round(min(r["d1_p_yes"] for r in pos), 6),
            "max_p_yes_not_ready": round(max(r["d1_p_yes"] for r in neg), 6),
            "false_approval_rate_wilson95_at_calibrated": wilson(c_d1_cal["fp"], len(neg)),
            "zero_false_approval_threshold_on_this_holdout": zero_fp_threshold(rows, "d1_p_yes"),
            "high_confidence_reject_gate": {
                "threshold": 0.90, "n": len(high_conf),
                "all_not_ready": all(not r["label"] for r in high_conf),
                "coverage_of_not_ready": f"{sum(1 for r in neg if r['d1_confidence'] >= 0.90)}/{len(neg)}",
            },
        },
        "full_model_generative": {
            "model": "gemini-3.8-flash",
            "endpoint": "POST /v1beta/models/gemini-3.8-flash:generateContent (one batched JSON-schema call)",
            "latency_s": 252.04,
            "finish_reason": fm["candidates"][0].get("finishReason"),
            "usage": fm.get("usageMetadata"),
            "confusion_boolean": c_fm_bool,
            "confusion_at_p_yes_0.5": confusion(fm_at_05, label),
            "brier": brier([r["fm_p_yes"] for r in rows], label),
            "mean_p_yes_ready": round(mean(r["fm_p_yes"] for r in pos), 4),
            "mean_p_yes_not_ready": round(mean(r["fm_p_yes"] for r in neg), 4),
            "false_approval_rate_wilson95_boolean": wilson(c_fm_bool["fp"], len(neg)),
            "zero_false_approval_threshold_on_this_holdout": zero_fp_threshold(rows, "fm_p_yes"),
        },
    },
    "comparison": {
        "decision_agreement_n": agree,
        "decision_agreement_rate": round(agree / len(rows), 4),
        "d1_false_approvals_at_calibrated": c_d1_cal["fp"],
        "fm_false_approvals_boolean": c_fm_bool["fp"],
        "d1_output_tokens": (d1.get("usage") or {}).get("total_output_tokens"),
        "fm_output_tokens": (fm.get("usageMetadata") or {}).get("candidatesTokenCount"),
        "d1_total_tokens": (d1.get("usage") or {}).get("total_tokens"),
        "fm_total_tokens": (fm.get("usageMetadata") or {}).get("totalTokenCount"),
    },
    "rows": rows,
}
json.dump(out, open(OUT, "w"), indent=2)
print("D1@cal", c_d1_cal)
print("FM bool", c_fm_bool)
print("brier D1/FM", out["arms"]["decisions_api"]["brier"], out["arms"]["full_model_generative"]["brier"])
print("agreement", out["comparison"])
print("zero-FP D1", out["arms"]["decisions_api"]["zero_false_approval_threshold_on_this_holdout"])
print("zero-FP FM", out["arms"]["full_model_generative"]["zero_false_approval_threshold_on_this_holdout"])
print("high-conf rejects", out["arms"]["decisions_api"]["high_confidence_reject_gate"])
