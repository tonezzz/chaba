#!/usr/bin/env python3
"""Baseline the 110-brief holdout against production's deterministic dispatch gate.

Replicates the read-only gates from ada-voice/opencode/ada_mcp.py:
  RISK_TERMS / _positive_risk_terms  (lines 120-143)
  _card_action / _resolved_verifier (lines 272-274, 2621-2632)
  ada_preflight start gates + dispatch fields (lines 2635-2689)

The current ada_preflight hardcodes typed_dispatch_available=False, so
ready_for_dispatch can never be true. We therefore report both the literal
current verdict and a "typed dispatch wired" counterfactual that drops only
that hardcoded gate. No API calls, no card mutation, no secrets.

Cards: a snapshot of origin/master docs/ssot/kanban/cards, default
/tmp/opencode/cards-baseline (CARDS_DIR overrides).
"""
import json
import os
from pathlib import Path
import re

import yaml

RESULTS = Path(__file__).resolve().parent / "results"
CARDS_DIR = Path(os.environ.get("CARDS_DIR", "/tmp/opencode/cards-baseline/docs/ssot/kanban/cards"))
DS = RESULTS / "g4-decision-gate-heldout110-dataset.json"
GRADED = RESULTS / "g4-decision-gate-heldout110-graded.json"
OUT = RESULTS / "g4-production-gate-baseline-20261127.json"

RISK_TERMS = (
    "deploy", "deployment", "production", "credential", "secret", "delete", "destructive",
    "database", "install", "systemd", "service", "origin", "restore",
    "timer", "rollout", "video", "render", "gpu", "mlx", "media",
    "rerender", "prune", "compact", "wp", "wordpress", "upsert",
)
NEGATION_RE = re.compile(
    r"\b(?:no|not|never|without|do\s+not|does\s+not|must\s+not|"
    r"blocked|prohibited|forbidden)\b[^.!?]{0,80}$",
    re.I,
)
READ_ONLY_PROFILES = {"ops-readonly", "ssot-research", "mddb-sequence", "storage-dryrun"}
REQUIRED = ("type", "repo", "executor", "model", "profile", "target_host", "artifact")
ALIASES = {"profile": ("profile", "agent_profile"), "artifact": ("artifact", "output_artifact")}


def positive_risk_terms(text):
    found = []
    lower = text.lower()
    for term in RISK_TERMS:
        for match in re.finditer(rf"\b{re.escape(term)}\b", lower):
            prefix = lower[max(0, match.start() - 100):match.start()]
            if not NEGATION_RE.search(prefix):
                found.append(term)
                break
    return found


def resolved_verifier(action):
    explicit = action.get("verify") or action.get("verifier")
    if explicit:
        return str(explicit)
    profile = str(action.get("agent_profile") or action.get("profile") or "").strip()
    if action.get("executor") == "opencode" and profile in READ_ONLY_PROFILES:
        return f"profile:{profile}"
    return None


card_paths = {}
for folder in (CARDS_DIR, CARDS_DIR / "archive"):
    for f in sorted(folder.glob("*.yml")):
        card_paths.setdefault(f.stem, f)

ds = json.load(open(DS))
graded = json.load(open(GRADED))
model_by_n = {r["n"]: r for r in graded["rows"]}

rows = []
for it in ds["items"]:
    path = card_paths.get(it["id"])
    card = (yaml.safe_load(open(path)) or {}) if path else {}
    action = card.get("action") if isinstance(card.get("action"), dict) else {}
    text = " ".join(str(card.get(k) or "") for k in ("title", "brief", "spec")).lower()
    risky = positive_risk_terms(text)
    missing = [
        field for field in REQUIRED
        if not any(action.get(name) for name in ALIASES.get(field, (field,)))
    ]
    verifier = resolved_verifier(action)
    if not verifier:
        missing.append("verifier")
    dispatch_ok = not missing
    gates = {
        "card_found": bool(path),
        "backlog": card.get("column") == "backlog",
        "no_open_requests": not bool(card.get("requests")),
        "safe_scope": not risky,
        "typed_dispatch_available": False,  # hardcoded in production today
    }
    wired_gates = {k: v for k, v in gates.items() if k != "typed_dispatch_available"}
    rows.append({
        "n": it["n"], "id": it["id"], "label": it["label"],
        "column": card.get("column"), "gates": gates, "risk_terms": risky,
        "dispatch_ok": dispatch_ok, "missing_fields": sorted(set(missing)),
        "verifier": verifier,
        "ready_current": all(gates.values()) and dispatch_ok,
        "ready_if_typed_wired": all(wired_gates.values()) and dispatch_ok,
        "d1_approve": model_by_n[it["n"]]["d1_p_yes"] >= 0.5161926625710843,
        "fm_approve": model_by_n[it["n"]]["fm_ready"],
    })


def confusion(pred, labels):
    tp = sum(1 for p, l in zip(pred, labels) if l and p)
    fn = sum(1 for p, l in zip(pred, labels) if l and not p)
    tn = sum(1 for p, l in zip(pred, labels) if not l and not p)
    fp = sum(1 for p, l in zip(pred, labels) if not l and p)
    return {"tp": tp, "fn": fn, "tn": tn, "fp": fp,
            "accuracy": round((tp + tn) / len(labels), 4),
            "approve_precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "approve_recall": round(tp / (tp + fn), 4) if tp + fn else None}


labels = [r["label"] for r in rows]
wired = [r["ready_if_typed_wired"] for r in rows]
current = [r["ready_current"] for r in rows]
gate_stats = {}
for gate in ("backlog", "no_open_requests", "safe_scope"):
    gate_stats[gate] = {
        "pass_ready": sum(1 for r in rows if r["label"] and r["gates"][gate]),
        "pass_not_ready": sum(1 for r in rows if not r["label"] and r["gates"][gate]),
    }
gate_stats["typed_dispatch_fields"] = {
    "pass_ready": sum(1 for r in rows if r["label"] and r["dispatch_ok"]),
    "pass_not_ready": sum(1 for r in rows if not r["label"] and r["dispatch_ok"]),
}

# Where a model judgment would add decisions beyond the wired production gate.
model_adds = []
for r in rows:
    if not r["ready_if_typed_wired"] and (r["d1_approve"] or r["fm_approve"]):
        model_adds.append({
            "n": r["n"], "id": r["id"], "label": r["label"],
            "d1_approve": r["d1_approve"], "fm_approve": r["fm_approve"],
            "blocked_by": [k for k, v in r["gates"].items() if not v]
                          + (["typed_dispatch_fields"] if not r["dispatch_ok"] else []),
        })

out = {
    "schema": "production-gate-baseline-110",
    "date": "2026-11-27",
    "source": "ada-voice/opencode/ada_mcp.py preflight gates; origin/master kanban-card snapshot",
    "caveat": "ada_preflight hardcodes typed_dispatch_available=False, so literal ready_for_dispatch is always false; the counterfactual drops only that gate.",
    "counts": {"ready": sum(labels), "not_ready": len(labels) - sum(labels)},
    "literal_current_gate": confusion(current, labels),
    "if_typed_dispatch_wired": confusion(wired, labels),
    "gate_stats": gate_stats,
    "per_gate_confusion": {
        gate: confusion([r["gates"][gate] for r in rows], labels)
        for gate in ("backlog", "no_open_requests", "safe_scope")
    },
    "semantic_gates_only": {
        "definition": "no_open_requests AND safe_scope; excludes workflow-state gates (backlog, typed envelope) and the hardcoded typed flag",
        "confusion": confusion(
            [r["gates"]["no_open_requests"] and r["gates"]["safe_scope"] for r in rows], labels
        ),
    },
    "model_added_approvals": {
        "n": len(model_adds),
        "of_which_ready": sum(1 for r in model_adds if r["label"]),
        "of_which_not_ready": sum(1 for r in model_adds if not r["label"]),
        "detail": model_adds,
    },
    "rows": rows,
}
json.dump(out, open(OUT, "w"), indent=2)
print("literal current", out["literal_current_gate"])
print("if wired", out["if_typed_dispatch_wired"])
print("gate stats", gate_stats)
print("model-added approvals", out["model_added_approvals"]["n"],
      "ready", out["model_added_approvals"]["of_which_ready"],
      "not_ready", out["model_added_approvals"]["of_which_not_ready"])
