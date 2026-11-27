#!/usr/bin/env python3
"""Build the balanced 110-brief held-out set used for the decision-1 vs full-model comparison.

55 READY / 55 NOT_READY, disjoint from the 60-brief train set and the earlier
41-brief fresh probe. Labels follow the trained gate's semantics: READY states
a concrete action and target with enough detail to act without another source;
NOT_READY defers to a note, says no action is needed, is a fixture, or is
blocked on approval. Ambiguous wording is excluded by explicit marker lists.

Inputs (env overrides):
  CARDS_DIR      directory holding kanban card YAML (default: a synced
                 origin/master snapshot under /tmp/opencode/d1cards2)
  TRAIN_DATASET  60-brief expanded dataset JSON
  PRIOR_DATASET  earlier 41-brief held-out dataset JSON
Outputs go to scripts/voice-bench/results/.
"""
import glob
import json
import os
from pathlib import Path
import re
import yaml

RESULTS = Path(__file__).resolve().parent / "results"
ROOT = os.environ.get("CARDS_DIR", "/tmp/opencode/d1cards2/docs/ssot/kanban/cards")
TRAIN = os.environ.get("TRAIN_DATASET", str(RESULTS / "g4-decision-gate-expanded-dataset.json"))
PRIOR = os.environ.get("PRIOR_DATASET", "/tmp/opencode/decision-gate-heldout-dataset.json")

NEG = [
    "details in the note", "nothing needed", "no action needed", "no further action",
    "test fixture", "blocked on approval", "awaiting approval", "approval required",
    "decision needed before", "human-owned step", "only after", "not yet",
    "waiting in the backlog", "parked", "deferred", "on hold", "not needed",
    "no-op", "informational", "for orientation", "tracker card", "umbrella card",
    "monitor only", "nothing to do", "nothing needed unless",
    "recurring session-audit signature", "read the note", "check the note",
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

train = json.load(open(TRAIN))
prior = json.load(open(PRIOR))
blocked = {i["id"] for i in train["items"]} | {i["id"] for i in prior["items"]}

rows = []
seen = set()
for f in sorted(glob.glob(os.path.join(ROOT, "*.yml")) + glob.glob(os.path.join(ROOT, "archive", "*.yml"))):
    cid = os.path.basename(f)[:-4]
    if cid in seen or cid in blocked or cid in EXCLUDE:
        continue
    if cid.startswith(("audit-miss-", "audit-oc-sequence-anomaly-", "bench-verifier-")):
        # Auto-generated incident findings, not dispatchable briefs.
        continue
    seen.add(cid)
    try:
        d = yaml.safe_load(open(f)) or {}
    except Exception:
        continue
    brief = str(d.get("brief") or "").replace("\n", " ").strip()
    if not (60 <= len(brief) <= 300):
        continue
    low = brief.lower()
    spec = bool(str(d.get("spec") or "").strip())
    source = "active" if os.path.dirname(f) == ROOT else "archive"
    if any(k in low for k in NEG):
        label = False
    elif spec and ACTION.search(brief) and not re.match(r"^(goal|idea|status|note|vision|question)\b", low):
        label = True
    elif not spec and not ACTION.search(brief):
        label = False
    else:
        continue
    rows.append({"id": cid, "brief": brief, "label": label, "source": source})

ready = [r for r in rows if r["label"]]
notready = [r for r in rows if not r["label"]]
digest = 0
capped = []
for r in notready:
    if "scheduled report-page job" in r["brief"]:
        digest += 1
        if digest > 10:
            continue
    capped.append(r)
notready = capped
print("pool ready", len(ready), "notready", len(notready))

sel = sorted(ready[:55] + notready[:55], key=lambda r: r["id"])
assert len({r["id"] for r in sel}) == len(sel) == 110
assert sum(r["label"] for r in sel) == 55

ds = {
    "schema": "decision-gate-heldout-110",
    "date": "2026-11-27",
    "source": "origin/master docs/ssot/kanban/cards/*.yml + archive/*.yml, disjoint from 60-brief train and 41-brief earlier probe",
    "label_rule": "READY: spec present, concrete action and target, no deferral/gating marker. NOT_READY: explicit deferral / no-action / fixture / approval-gated marker, or descriptive-only with no spec. Ambiguous cards manually excluded.",
    "counts": {"ready": 55, "not_ready": 55},
    "items": [{"n": i + 1, **r} for i, r in enumerate(sel)],
}
json.dump(ds, open(RESULTS / "g4-decision-gate-heldout110-dataset.json", "w"), indent=2)

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
json.dump(payload, open(RESULTS / "g4-decision-gate-heldout110-payload.json", "w"), indent=2)
open(RESULTS / "g4-decision-gate-heldout110-review.txt", "w").write("\n".join(
    ("R" if r["label"] else "N") + " " + l for r, l in zip(sel, lines)) + "\n")
print("selected 110", ds["counts"], "input chars", len(payload["input"]), "questions", len(questions))
