#!/usr/bin/env python3
"""Build an independent 130-brief validation set (60 READY / 70 NOT_READY).

Disjoint by card ID and normalized brief text from all three prior sets:
the 60-brief train set, the 41-brief earlier probe, and the 110-brief holdout.
Negatives are deliberately "hard": they contain an action verb plus an
explicit deferral / approval-gate / no-action marker, so they superficially
look dispatchable; descriptive-only no-spec briefs fill the remainder.

Inputs (env overrides):
  CARDS_DIR      origin/master kanban-card snapshot
  TRAIN_DATASET  60-brief expanded dataset JSON
  PRIOR_DATASET  earlier 41-brief held-out dataset JSON
  HOLDOUT_DATASET  110-brief held-out dataset JSON
Outputs go to scripts/voice-bench/results/.
"""
import glob
import json
import os
import re
from pathlib import Path
import yaml

RESULTS = Path(__file__).resolve().parent / "results"
CARDS_DIR = Path(os.environ.get("CARDS_DIR", "/tmp/opencode/cards-baseline/docs/ssot/kanban/cards"))
TRAIN = Path(os.environ.get("TRAIN_DATASET", str(RESULTS / "g4-decision-gate-expanded-dataset.json")))
PRIOR = Path(os.environ.get("PRIOR_DATASET", "/tmp/opencode/decision-gate-heldout-dataset.json"))
HOLDOUT = RESULTS / "g4-decision-gate-heldout110-dataset.json"
TARGET_READY = 60
TARGET_NOT_READY = 70

NEG = [
    "details in the note", "nothing needed", "no action needed", "no further action",
    "test fixture", "blocked on approval", "awaiting approval", "approval required",
    "decision needed before", "human-owned step", "only after", "not yet",
    "waiting in the backlog", "parked", "deferred", "on hold", "not needed",
    "no-op", "informational", "for orientation", "tracker card", "umbrella card",
    "monitor only", "nothing to do", "nothing needed unless",
    "recurring session-audit signature", "read the note", "check the note",
    "do not dispatch", "not dispatchable", "needs tony", "needs approval",
    "pending approval", "after approval", "once approved", "human review required",
    "hold until", "no owner", "not assigned", "backlog only", "someday",
]
ACTION = re.compile(
    r"\b(verify|build|make|authorize|ground|update|fix|add|investigate|reconcile|"
    r"audit|check|evaluate|deploy|redeploy|publish|document|record|review|compare|"
    r"create|remove|restore|migrate|configure|enable|disable|implement|close|"
    r"clarify|measure|probe|run|test|confirm|resolve|trim|align|upgrade|switch|"
    r"re-run|rerun|schedule|extend|coordinate|lock in|rebuild|route|stop|preserve|"
    r"benchmark|re-keyword|give|harden|write|finish|complete|prune|report|sweep|"
    r"keep|drop|seal|wire|land|sync|mend|rekey|replace|retire|split|fold|map)\b",
    re.I,
)
# Manual review of the deterministic READY pool: scratch fixtures, approval
# gates, descriptive-only audit reports, and standing wishes without a
# concrete action/target. Moved to negatives before selection so the balance
# stays 60/70.
LABEL_OVERRIDES = {
    "board-cli-ask-verify-scratch", "board-diagram-lanes-view",
    "capture-harvester-apply-gate-1426cfed", "chaba-exec-checkout-idc02-dirty-files",
    "devin-lane-cheap-ops-reroute", "devin-session-audit-2026-10-29",
    "devin-taskdir-gc-dispatch-hosts", "devnest-news-watch-procedure",
    "jev-code-decision-layer-construct-templa-77e184", "kk-mac-disk-headroom",
    "job-health-sweep-consecutive-failure-alerts", "dispatch-worktree-gc",
    "info-find-efficiency-benchmark", "jack-opencode-project-directory-creation",
    "kk-mac-ansible-ssh-key-seeding", "mcp-dell-alphavantage-llama-decision",
    "mddb-storage-reduction-retention-relocation", "lesson-polish-run",
    "jevnest-kk-mac-capacity-loop",
}
EXCLUDE = {
    "ada-ocb-skills-wiki-education-2026-11-24", "card-runner-lifecycle-test",
    "diagnose-unattended-devin-session-storm-20261108",
    "audit-ollama-service-tony-dell", "board-write-lock-scope-narrowing",
    "prune-old-docs-sweep-exits-in-223ms-veri-6e0db7",
    "chat-send-photos-picker", "dispatch-priority-order",
    "nest-lane-metrics", "devnest-news-promote-wp4010",
    "idc02-runner-smoke", "ops-incident-ladder", "precommit-warning-baseline",
    "lab-mddb-quantized", "logs-digest-program", "dev-ha-edge",
    "ada-market-tool", "ada-dead-turn-guard", "ada-kanban-access",
    "scenario-report-opinion", "eval-ide-antigravity", "gev-program-design",
    "starboard-windsurf-catalogs", "request-lifecycle",
    "ada-kk-dance-party-video-longer", "ada-voice-host-status-drop-19-pr",
    "ada-voice-map-embed-pr22-merge-deploy", "ansible-benchmark-stagger-hook-mode-0775",
    "ada-write-fidelity-drop-parity", "ada-ocb-free-lane-workflow-pilot",
    "ansible-benchmark-ssot-duplicate-action-430", "ada-card-runner",
}

blocked_ids, blocked_briefs = set(), set()
for p in (TRAIN, PRIOR, HOLDOUT):
    for it in json.load(open(p))["items"]:
        blocked_ids.add(it["id"])
        blocked_briefs.add(re.sub(r"\W+", " ", it["brief"].lower()).strip())

cards = {}
for folder in (CARDS_DIR, CARDS_DIR / "archive"):
    for f in sorted(folder.glob("*.yml")):
        cards.setdefault(f.stem, (f, folder == CARDS_DIR))

ready, hard_neg, plain_neg = [], [], []
for cid, (path, active) in sorted(cards.items()):
    if cid in blocked_ids or cid in EXCLUDE:
        continue
    if cid.startswith(("audit-miss-", "audit-oc-sequence-anomaly-", "bench-verifier-")):
        continue
    try:
        d = yaml.safe_load(open(path)) or {}
    except Exception:
        continue
    brief = str(d.get("brief") or "").replace("\n", " ").strip()
    if not (60 <= len(brief) <= 300):
        continue
    norm = re.sub(r"\W+", " ", brief.lower()).strip()
    if norm in blocked_briefs:
        continue
    low = brief.lower()
    spec = bool(str(d.get("spec") or "").strip())
    action = bool(ACTION.search(brief))
    marker = next((k for k in NEG if k in low), None)
    source = "active" if active else "archive"
    if spec and action and not marker and not re.match(r"^(goal|idea|status|note|vision|question)\b", low):
        ready.append({"id": cid, "brief": brief, "label": True, "source": source, "kind": "ready"})
    elif marker:
        hard_neg.append({"id": cid, "brief": brief, "label": False, "source": source,
                         "kind": "hard_negative", "marker": marker, "has_action_verb": action})
    elif not spec and not action:
        plain_neg.append({"id": cid, "brief": brief, "label": False, "source": source,
                          "kind": "descriptive_negative"})

overridden = [r for r in ready if r["id"] in LABEL_OVERRIDES]
ready = [r for r in ready if r["id"] not in LABEL_OVERRIDES]
for r in overridden:
    r.update({"label": False, "kind": "manual_override_negative", "marker": "manual review",
              "has_action_verb": True})
    hard_neg.append(r)
print("pools:", "ready", len(ready), "hard_neg", len(hard_neg), "plain_neg", len(plain_neg),
      "manual_overrides", len(overridden))


def cap_digest(rows, cap=5):
    out, seen = [], 0
    for r in rows:
        if "scheduled report-page job" in r["brief"]:
            seen += 1
            if seen > cap:
                continue
        out.append(r)
    return out


hard_neg = cap_digest(hard_neg)
plain_neg = cap_digest(plain_neg)
negatives = hard_neg[:TARGET_NOT_READY]
if len(negatives) < TARGET_NOT_READY:
    negatives += plain_neg[: TARGET_NOT_READY - len(negatives)]
sel = sorted(ready[:TARGET_READY] + negatives, key=lambda r: r["id"])
assert len({r["id"] for r in sel}) == len(sel) == TARGET_READY + TARGET_NOT_READY
assert sum(r["label"] for r in sel) == TARGET_READY
assert len({re.sub(r"\W+", " ", r["brief"].lower()).strip() for r in sel}) == len(sel)

ds = {
    "schema": "decision-gate-validation-130",
    "date": "2026-11-27",
    "source": "origin/master docs/ssot/kanban/cards snapshot, disjoint by ID and normalized brief from 60-brief train, 41-brief earlier probe, and 110-brief holdout",
    "label_rule": "READY: spec present, concrete action and target, no deferral/gating marker. NOT_READY: explicit deferral / no-action / fixture / approval-gated marker (priority, including action-bearing 'hard' negatives), or descriptive-only with no spec and no action verb. Ambiguous cards manually excluded.",
    "counts": {"ready": TARGET_READY, "not_ready": TARGET_NOT_READY},
    "negative_mix": {
        "hard_negatives": sum(1 for r in sel if r.get("kind") == "hard_negative"),
        "hard_negatives_with_action_verb": sum(1 for r in sel if r.get("has_action_verb")),
        "descriptive_negatives": sum(1 for r in sel if r.get("kind") == "descriptive_negative"),
    },
    "items": [{"n": i + 1, **r} for i, r in enumerate(sel)],
}
json.dump(ds, open(RESULTS / "g4-decision-gate-validation130-dataset.json", "w"), indent=2)

lines = [f"{i+1}. [{r['id']}] {r['brief']}" for i, r in enumerate(sel)]
questions = {}
for i in range(len(sel)):
    questions[f"ready_{i+1}"] = {
        "type": "noul",
        "instructions": (
            f"Is brief {i+1} ready for dispatch now? Ready means it states a concrete action "
            "and target with enough detail to act without another source; not ready means it "
            "defers to a note, says no action is needed, is a test fixture, or is blocked on approval."
        ),
    }
payload = {
    "model": "gemini-decision-1",
    "input": "Kanban card briefs to triage:\n" + "\n".join(lines),
    "questions": questions,
}
json.dump(payload, open(RESULTS / "g4-decision-gate-validation130-payload.json", "w"), indent=2)
open(RESULTS / "g4-decision-gate-validation130-review.txt", "w").write("\n".join(
    ("R" if r["label"] else "N") + " " + l for r, l in zip(sel, lines)) + "\n")
print("selected", ds["counts"], ds["negative_mix"], "input chars", len(payload["input"]), "questions", len(questions))
