#!/usr/bin/env python3
"""Grade the Decisions API rubric probe against the 130-brief validation set.

Compares three calibrated signals from the same shared input:
  noul     - prior binary arm (p_yes)
  score    - expected rubric level 0..3, normalized to 0..1
  choice   - P(option == 'ready') from the disposition choice

Threshold sweeps are exploratory: any zero-FP threshold found here is tuned on
the same set and needs another disjoint holdout before adoption. Fixed 0.5
thresholds and the top-choice rule are the primary comparisons.

No API calls; no secrets.
"""
import json
import math
from pathlib import Path
from statistics import mean

RESULTS = Path(__file__).resolve().parent / "results"
DS = RESULTS / "g4-decision-gate-validation130-dataset.json"
NOUL = RESULTS / "g4-decision-gate-validation130-response.json"
RUB = RESULTS / "g4-decision-gate-rubric130-response.json"
OUT = RESULTS / "g4-decision-gate-rubric130-graded.json"
LABEL_CORRECTIONS = {"gemini-dev-capabilities-research-2026-11-26",
                    "opencode-safe-storage-cleanup-report"}

ds = json.load(open(DS))
noul = json.load(open(NOUL))["answers"]
rub = json.load(open(RUB))["answers"]

rows = []
for it in ds["items"]:
    n = it["n"]
    s = rub[f"score_{n}"]
    c = rub[f"choice_{n}"]
    rows.append({
        "n": n, "id": it["id"], "label": it["label"],
        "brief": it["brief"], "kind": it.get("kind"),
        "p_yes": noul[f"ready_{n}"]["noul"],
        "noul_conf": noul[f"ready_{n}"].get("confidence"),
        "score": s["score"], "score_norm": s["score"] / 3,
        "score_conf": s["confidence"], "p_level3": s["probabilities"].get("3", 0),
        "p_level0": s["probabilities"].get("0", 0),
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


def zero_fp_threshold(rows, key, labels):
    best = None
    for t in sorted({r[key] for r in rows} | {0.0, 1.0}):
        c = confusion([r[key] >= t for r in rows], labels)
        if c["fp"] == 0 and c["tp"] > 0:
            if best is None or c["tp"] > best[1]["tp"] or (c["tp"] == best[1]["tp"] and t > best[0]):
                best = (t, c)
    return {"threshold": round(best[0], 6), "confusion": best[1],
            "false_approval_wilson95": wilson(best[1]["fp"], sum(1 for l in labels if not l))} if best else None


def fixed_arms(key, labels):
    return {f"at_{t}": {"threshold": t, "confusion": confusion([r[key] >= t for r in rows], labels)}
            for t in (0.5, 0.536574)}


labels = [r["label"] for r in rows]
corrected = [True if r["id"] in LABEL_CORRECTIONS else r["label"] for r in rows]
n_neg = sum(1 for l in labels if not l)

# Fixed-threshold comparisons, plus top-choice rule.
arms = {
    "noul": fixed_arms("p_yes", corrected),
    "score_norm": fixed_arms("score_norm", corrected),
    "choice_p_ready": fixed_arms("p_ready", corrected),
    "score_p_level3": fixed_arms("p_level3", corrected),
    "choice_top_is_ready": {
        "confusion": confusion([r["choice"] == "ready" for r in rows], corrected),
    },
}
for arm, key in (("noul", "p_yes"), ("score_norm", "score_norm"),
                 ("choice_p_ready", "p_ready"), ("score_p_level3", "p_level3")):
    arms[arm]["brier"] = brier([r[key] for r in rows], corrected)
    arms[arm]["zero_fp_sweep_exploratory"] = zero_fp_threshold(rows, key, corrected)
    arms[arm]["as_built_labels"] = {
        t: confusion([r[key] >= t for r in rows], labels) for t in (0.5, 0.536574)
    }

# Composed rule (docs recommend combining atomic checks in code): require both
# a high P(ready) and a high normalized rubric score. Grid reported as
# exploratory only; tuned on this set.
grid = []
for pr in [round(x * 0.01, 2) for x in range(50, 96)]:
    for sn in [round(x * 0.01, 2) for x in range(50, 96)]:
        c = confusion([r["p_ready"] >= pr and r["score_norm"] >= sn for r in rows], corrected)
        if c["fp"] == 0 and c["tp"] > 0:
            grid.append({"p_ready": pr, "score_norm": sn, "tp": c["tp"], "recall": c["approve_recall"]})
grid_best = sorted(grid, key=lambda g: (-g["tp"], g["p_ready"] + g["score_norm"]))[:5]

# Refined auto-reject shortcut: confidently NO, not merely high confidence.
reject_checks = {
    "noul_confident_no": {
        "pred": [not (r["p_yes"] <= 0.1 and (r["noul_conf"] or 0) >= 0.9) for r in rows],
        "rule": "reject when p_yes <= 0.10 and confidence >= 0.90",
    },
    "score_confident_low": {
        "pred": [not (r["p_level3"] <= 0.05 and r["score_conf"] >= 0.9) for r in rows],
        "rule": "reject when P(level 3) <= 0.05 and score confidence >= 0.90",
    },
    "choice_confident_not_ready": {
        "pred": [not (r["p_ready"] <= 0.1 and r["choice_conf"] >= 0.9) for r in rows],
        "rule": "reject when P(ready) <= 0.10 and choice confidence >= 0.90",
    },
}
shortcuts = {}
for name, ch in reject_checks.items():
    c = confusion(ch["pred"], corrected)
    shortcuts[name] = {
        "rule": ch["rule"], "confusion_if_approve_otherwise": c,
        "rejected": sum(1 for p in ch["pred"] if not p),
        "false_rejected_ready": [r["id"] for i, (r, p) in enumerate(zip(rows, ch["pred"]))
                                 if not p and corrected[i]],
        "as_built_false_rejected_ready": [
            r["id"] for r, p in zip(rows, ch["pred"]) if not p and r["label"]
        ],
        "as_built_rejected": sum(1 for p, l in zip(ch["pred"], labels) if not p and not l),
    }

out = {
    "schema": "decision-gate-rubric-130-graded",
    "date": "2026-11-27",
    "source": "Decisions API score + choice questions over the identical 130-brief shared input",
    "labels": {
        "primary": "as-built deterministic labels",
        "comparison": "corrected labels for the two documented marker misfires",
        "corrected_ids": sorted(LABEL_CORRECTIONS),
    },
    "usage": json.load(open(RUB)).get("usage"),
    "arms": arms,
    "composed_rule_grid_exploratory": {
        "note": "Tuned on this validation set; needs a fresh disjoint holdout before adoption.",
        "best": grid_best, "n_zero_fp_cells": len(grid),
    },
    "confident_reject_shortcuts": shortcuts,
    "top_choice_errors": {
        "false_approvals": [{"n": r["n"], "id": r["id"], "label": r["label"],
                             "corrected_label": corrected[i], "p_ready": r["p_ready"],
                             "score": r["score"], "p_yes": r["p_yes"]}
                            for i, r in enumerate(rows)
                            if r["choice"] == "ready" and not corrected[i]],
        "false_rejects": [{"n": r["n"], "id": r["id"], "label": r["label"],
                           "corrected_label": corrected[i], "p_ready": r["p_ready"],
                           "choice": r["choice"], "score": r["score"]}
                          for i, r in enumerate(rows)
                          if r["choice"] != "ready" and corrected[i]],
    },
    "disagreements": {
        "score_vs_noul_at_0.5": [
            {"n": r["n"], "id": r["id"], "label": r["label"], "p_yes": r["p_yes"],
             "score_norm": r["score_norm"], "p_ready": r["p_ready"]}
            for r in rows if (r["p_yes"] >= 0.5) != (r["score_norm"] >= 0.5)
        ],
    },
    "rows": rows,
}
json.dump(out, open(OUT, "w"), indent=2)

print("usage", out["usage"])
for key in ("noul", "score_norm", "choice_p_ready", "score_p_level3"):
    print(key, "brier", arms[key]["brier"],
          "at0.5", arms[key]["at_0.5"]["confusion"],
          "zeroFP", arms[key]["zero_fp_sweep_exploratory"]["threshold"],
          arms[key]["zero_fp_sweep_exploratory"]["confusion"]["approve_recall"])
print("top-choice ready", arms["choice_top_is_ready"]["confusion"])
print("composed best", grid_best[:3], "cells", len(grid))
for name, v in shortcuts.items():
    print(name, "rejected", v["rejected"], "false-ready-rejects", len(v["false_rejected_ready"]))
print("disagreements score vs noul @0.5", len(out["disagreements"]["score_vs_noul_at_0.5"]))
