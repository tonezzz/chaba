#!/usr/bin/env python3
"""Grade the paired choice vs binary noul arms on the diverse-negative set.

Both arms used the same 60-brief shared input and the hand-audited labels.
No API calls, no secrets.

Threshold sweeps are exploratory and tuned on this set; the fixed 0.5
threshold and the top-choice rule are the primary paired comparisons.
"""
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

RESULTS = Path(__file__).resolve().parent / "results"
ds = json.load(open(RESULTS / "g4-decision-gate-diverse60-dataset.json"))
noul = json.load(open(RESULTS / "g4-decision-gate-diverse60-response.json"))["answers"]
choice = json.load(open(RESULTS / "g4-decision-gate-diverse60-choice-response.json"))["answers"]
usage_choice = json.load(open(RESULTS / "g4-decision-gate-diverse60-choice-response.json"))["usage"]
assert len(ds["items"]) == len(noul) == len(choice) == 60

rows = []
for it in ds["items"]:
    n = it["n"]
    nr, cr = noul[f"ready_{n}"], choice[f"choice_{n}"]
    rows.append({
        "n": n, "id": it["id"], "brief": it["brief"], "label": it["label"],
        "kind": it["kind"], "label_reason": it["label_reason"],
        "p_yes": nr["noul"], "noul_conf": nr.get("confidence"),
        "choice": cr["choice"], "p_ready": cr["probabilities"].get("ready", 0),
        "choice_conf": cr.get("confidence"),
        "choice_probs": cr["probabilities"],
    })

THRESHOLDS = {"default": 0.5, "train_calibrated": 0.5161926625710843,
              "holdout_zero_fp": 0.536574}
ARGUABLE = {
    "kk-mac-script-smoke", "cast-loop-breaker-test-failure", "keywatch-or-idc03",
    "keywatch-or-tony-dell", "keywatch-or-tony-omen", "devin-taskdir-gc-dispatch-hosts",
}
labels = [r["label"] for r in rows]
generous = [True if r["id"] in ARGUABLE else r["label"] for r in rows]
n_neg = sum(1 for l in labels if not l)


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


def zero_fp(rows, key, labs):
    best = None
    for t in sorted({r[key] for r in rows} | {0.0, 1.0}):
        c = confusion([r[key] >= t for r in rows], labs)
        if c["fp"] == 0 and c["tp"] > 0:
            if best is None or c["tp"] > best[1]["tp"] or (c["tp"] == best[1]["tp"] and t > best[0]):
                best = (t, c)
    return {"threshold": round(best[0], 6), "confusion": best[1]} if best else None


def arms_for(key, labs):
    out = {}
    for name, t in THRESHOLDS.items():
        c = confusion([r[key] >= t for r in rows], labs)
        out[name] = {"threshold": t, "confusion": c,
                     "false_approval_rate_wilson95": wilson(c["fp"], sum(1 for l in labs if not l))}
    return out


primary = {
    "noul": arms_for("p_yes", labels),
    "choice": arms_for("p_ready", labels),
}
brier = {
    "noul": round(mean((r["p_yes"] - (1 if r["label"] else 0)) ** 2 for r in rows), 4),
    "choice": round(mean((r["p_ready"] - (1 if r["label"] else 0)) ** 2 for r in rows), 4),
}
top_choice = confusion([r["choice"] == "ready" for r in rows], labels)

# Paired decisions at the primary 0.5 threshold.
paired = defaultdict(list)
for r in rows:
    a, b = r["p_yes"] >= 0.5, r["p_ready"] >= 0.5
    paired[(a, b)].append(r)
paired_summary = {}
for (a, b), rs in sorted(paired.items()):
    key = ("both_approve" if a and b else "noul_only_approve" if a else
           "choice_only_approve" if b else "both_reject")
    paired_summary[key] = {
        "n": len(rs),
        "truly_ready": sum(1 for r in rs if r["label"]),
        "not_ready": sum(1 for r in rs if not r["label"]),
        "ids": [r["id"] for r in rs],
    }

by_family = {}
for fam in sorted({r["kind"] for r in rows if not r["label"]}):
    fr = [r for r in rows if not r["label"] and r["kind"] == fam]
    by_family[fam] = {
        "n": len(fr),
        "noul_fp_at_0.5": [r["id"] for r in fr if r["p_yes"] >= 0.5],
        "choice_fp_at_0.5": [r["id"] for r in fr if r["p_ready"] >= 0.5],
        "mean_p_yes": round(mean(r["p_yes"] for r in fr), 4),
        "mean_p_ready": round(mean(r["p_ready"] for r in fr), 4),
    }

shortcuts = {
    "noul_confident_no": {
        "rule": "reject when p_yes <= 0.10 and confidence >= 0.90",
        "ids": [r["id"] for r in rows if r["p_yes"] <= 0.10 and (r["noul_conf"] or 0) >= 0.90],
        "false_rejects": [r["id"] for r in rows if r["label"] and r["p_yes"] <= 0.10
                          and (r["noul_conf"] or 0) >= 0.90],
        "coverage_of_not_ready": f"{sum(1 for r in rows if not r['label'] and r['p_yes'] <= 0.10 and (r['noul_conf'] or 0) >= 0.90)}/{n_neg}",
    },
    "choice_confident_not_ready": {
        "rule": "reject when p_ready <= 0.10 and confidence >= 0.90",
        "ids": [r["id"] for r in rows if r["p_ready"] <= 0.10 and (r["choice_conf"] or 0) >= 0.90],
        "false_rejects": [r["id"] for r in rows if r["label"] and r["p_ready"] <= 0.10
                          and (r["choice_conf"] or 0) >= 0.90],
        "coverage_of_not_ready": f"{sum(1 for r in rows if not r['label'] and r['p_ready'] <= 0.10 and (r['choice_conf'] or 0) >= 0.90)}/{n_neg}",
    },
}

sensitivity = {
    name: {
        "noul": arms_for("p_yes", generous),
        "choice": arms_for("p_ready", generous),
    }
    for name in ("generous_labels",)
}

out = {
    "schema": "decision-gate-diverse60-choice-graded",
    "date": "2026-11-27",
    "source": "Choice and binary noul questions over the identical 60-brief diverse-negative shared input",
    "usage_choice": usage_choice,
    "brier": brier,
    "primary_arms": primary,
    "top_choice_is_ready": top_choice,
    "zero_fp_sweeps_exploratory": {
        "noul": zero_fp(rows, "p_yes", labels),
        "choice": zero_fp(rows, "p_ready", labels),
    },
    "paired_at_0.5": paired_summary,
    "negative_family_breakdown": by_family,
    "confident_reject_shortcuts": shortcuts,
    "label_ambiguity_sensitivity": {
        "description": "Same six arguably dispatchable negatives as the noul grading; primary labels unchanged.",
        "reclassified_ids": sorted(ARGUABLE),
        "arms": sensitivity["generous_labels"],
    },
    "rows": rows,
}
json.dump(out, open(RESULTS / "g4-decision-gate-diverse60-choice-graded.json", "w"), indent=2)
for arm in ("noul", "choice"):
    for name, v in primary[arm].items():
        print(arm, name, v["confusion"], "wilson", v["false_approval_rate_wilson95"])
    print(arm, "brier", brier[arm], "zeroFP", out["zero_fp_sweeps_exploratory"][arm])
print("top_choice", top_choice)
print("paired", {k: (v["n"], v["truly_ready"], v["not_ready"]) for k, v in paired_summary.items()})
print("shortcuts", shortcuts)
