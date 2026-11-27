#!/usr/bin/env python3
"""Grade the rubric cross-check on the original 110-brief holdout.

Uses the final Tony-reviewed labels from the 110 graded artifact and the exact
score/choice criteria used on the 130-brief validation set. No API calls.
"""
import json
import math
from pathlib import Path
from statistics import mean

RESULTS = Path(__file__).resolve().parent / "results"
DS = RESULTS / "g4-decision-gate-heldout110-dataset.json"
NOUL = RESULTS / "g4-decision-gate-heldout110-graded.json"
RUB = RESULTS / "g4-decision-gate-rubric110-response.json"
OUT = RESULTS / "g4-decision-gate-rubric110-graded.json"

ds = json.load(open(DS))
noul = {r["n"]: r for r in json.load(open(NOUL))["rows"]}
rub = json.load(open(RUB))["answers"]

rows = []
for it in ds["items"]:
    n = it["n"]
    s, c = rub[f"score_{n}"], rub[f"choice_{n}"]
    rows.append({
        "n": n, "id": it["id"], "label": bool(noul[n]["label"]), "brief": it["brief"],
        "p_yes": noul[n]["d1_p_yes"], "noul_conf": noul[n]["d1_confidence"],
        "score": s["score"], "score_norm": s["score"] / 3, "score_conf": s["confidence"],
        "p_level3": s["probabilities"].get("3", 0),
        "choice": c["choice"], "p_ready": c["probabilities"].get("ready", 0),
        "choice_conf": c["confidence"],
    })


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


def zero_fp_threshold(key, labels):
    best = None
    for t in sorted({r[key] for r in rows} | {0.0, 1.0}):
        c = confusion([r[key] >= t for r in rows], labels)
        if c["fp"] == 0 and c["tp"] > 0:
            if best is None or c["tp"] > best[1]["tp"] or (c["tp"] == best[1]["tp"] and t > best[0]):
                best = (t, c)
    return {"threshold": round(best[0], 6), "confusion": best[1],
            "false_approval_wilson95": wilson(best[1]["fp"], sum(1 for l in labels if not l))} if best else None


labels = [r["label"] for r in rows]
arms = {
    "noul": {
        "at_0.5": confusion([r["p_yes"] >= 0.5 for r in rows], labels),
        "at_0.5162": confusion([r["p_yes"] >= 0.5161926625710843 for r in rows], labels),
        "at_0.536574": confusion([r["p_yes"] >= 0.536574 for r in rows], labels),
        "brier": brier([r["p_yes"] for r in rows], labels),
    },
    "choice_p_ready": {
        "at_0.5": confusion([r["p_ready"] >= 0.5 for r in rows], labels),
        "brier": brier([r["p_ready"] for r in rows], labels),
        "zero_fp_sweep_exploratory": zero_fp_threshold("p_ready", labels),
    },
    "choice_top_is_ready": {
        "confusion": confusion([r["choice"] == "ready" for r in rows], labels),
    },
    "score_norm": {
        "at_0.5": confusion([r["score_norm"] >= 0.5 for r in rows], labels),
        "brier": brier([r["score_norm"] for r in rows], labels),
    },
    "score_p_level3": {
        "at_0.5": confusion([r["p_level3"] >= 0.5 for r in rows], labels),
        "brier": brier([r["p_level3"] for r in rows], labels),
    },
}

shortcuts = {}
for name, fn, key, ckey in (
    ("noul_confident_no", lambda r: r["p_yes"] <= 0.1 and r["noul_conf"] >= 0.9, "p_yes", "noul_conf"),
    ("choice_confident_not_ready", lambda r: r["p_ready"] <= 0.1 and r["choice_conf"] >= 0.9, "p_ready", "choice_conf"),
):
    rejected = [r for r in rows if fn(r)]
    shortcuts[name] = {
        "rejected": len(rejected),
        "false_rejected_ready": [{"id": r["id"], key: round(r[key], 4)}
                                 for r in rejected if r["label"]],
        "coverage_of_not_ready": f"{sum(1 for r in rejected if not r['label'])}/{sum(1 for l in labels if not l)}",
    }

out = {
    "schema": "decision-gate-rubric-110-graded",
    "date": "2026-11-27",
    "purpose": "Cross-check the 130-brief rubric finding on the original 110-brief holdout with Tony-reviewed labels.",
    "usage": json.load(open(RUB)).get("usage"),
    "arms": arms,
    "confident_reject_shortcuts": shortcuts,
    "top_choice_errors": {
        "false_approvals": [{"n": r["n"], "id": r["id"], "p_ready": r["p_ready"]}
                            for r in rows if r["choice"] == "ready" and not r["label"]],
        "false_rejects": [{"n": r["n"], "id": r["id"], "p_ready": r["p_ready"]}
                          for r in rows if r["choice"] != "ready" and r["label"]],
    },
    "rows": rows,
}
json.dump(out, open(OUT, "w"), indent=2)
for name, arm in arms.items():
    print(name, {k: v for k, v in arm.items() if k != "zero_fp_sweep_exploratory"},
          arm.get("zero_fp_sweep_exploratory", ""))
print("shortcuts", json.dumps(shortcuts, indent=1))
print("top choice errors", json.dumps(out["top_choice_errors"], indent=1))
