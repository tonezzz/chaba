#!/usr/bin/env python3
"""Build a balanced, non-duplicated decision-gate dataset and batch payload.

Sources: repo kanban cards at origin/master (active + archive), extracted to
/tmp/opencode/d1cards. Deterministic labeling from the existing label rule.
"""
import glob
import hashlib
import json
import os
import re
import yaml

ROOT = "/tmp/opencode/d1cards/docs/ssot/kanban/cards"
NEG = (
    "no action needed", "nothing needed", "leave it alone", "details in the note",
    "test fixture", "blocked on", "awaiting", "waiting in the backlog",
    "parked", "deferred", "on hold", "not needed", "no-op", "informational",
)
VERBS = (
    "verify", "build", "make", "authorize", "ground", "update", "fix", "add",
    "investigate", "reconcile", "audit", "check", "evaluate", "deploy",
    "redeploy", "publish", "document", "record", "review", "compare",
    "create", "remove", "restore", "migrate", "configure", "enable",
    "disable", "implement", "close", "clarify", "measure", "probe", "run",
)
# Explicitly adjudicated in the first eval or visibly ambiguous under the rule.
EXCLUDE = {
    "ada-ocb-skills-wiki-education-2026-11-24",  # already adjudicated READY by Tony
    "card-runner-lifecycle-test",                # test fixture despite imperative wording
    "diagnose-unattended-devin-session-storm-20261108",  # mixed action + "keep paused until understood"
    "audit-ollama-service-tony-dell",            # tool name at start, not a clear imperative
    "board-write-lock-scope-narrowing",           # "no-op" marker but actionable wording
    "prune-old-docs-sweep-exits-in-223ms-veri-6e0db7",  # "no-ops" marker but an investigation
    "chat-send-photos-picker",                 # problem statement, not a clear imperative
    "dispatch-priority-order",                  # "parked" appears as a noun, not a deferral marker
}


def load():
    out = []
    for f in glob.glob(os.path.join(ROOT, "*.yml")) + glob.glob(os.path.join(ROOT, "archive", "*.yml")):
        try:
            d = yaml.safe_load(open(f)) or {}
        except Exception:
            continue
        cid = os.path.basename(f)[:-4]
        brief = str(d.get("brief") or "").replace("\n", " ").strip()
        spec = bool(str(d.get("spec") or "").strip())
        if cid in EXCLUDE or not (60 <= len(brief) <= 300):
            continue
        source = "active" if os.path.dirname(f) == ROOT else "archive"
        out.append({"id": cid, "brief": brief, "spec": spec, "source": source})
    return out


def label(r):
    low = r["brief"].lower()
    if any(k in low for k in NEG):
        return False
    if r["spec"] and re.match(r"^(" + "|".join(VERBS) + r")\b", r["brief"], re.I):
        return True
    return None


rows = load()
# Same card id can exist in both active and archive; keep the active copy.
seen = set()
deduped = []
for r in sorted(rows, key=lambda x: (x["id"], x["source"] != "active")):
    if r["id"] in seen:
        continue
    seen.add(r["id"])
    deduped.append(r)
rows = deduped
ready, notready = [], []
# Cap near-duplicate template briefs (digest family) to 5.
digest_count = 0
for r in sorted(rows, key=lambda x: x["id"]):
    lab = label(r)
    if lab is True:
        ready.append(r)
    elif lab is False:
        if "scheduled report-page job" in r["brief"]:
            if digest_count >= 5:
                continue
            digest_count += 1
        notready.append(r)

# Balance 30/30, favouring active cards in each class.
def pick(pool, limit, want_active):
    active = [r for r in pool if r["source"] == "active"]
    archive = [r for r in pool if r["source"] == "archive"]
    chosen = active[:want_active] + archive[:limit - want_active]
    if len(chosen) < limit:
        chosen += [r for r in active + archive if r not in chosen][:limit - len(chosen)]
    return chosen[:limit]

selected = pick(ready, 30, 15) + pick(notready, 30, 10)
selected.sort(key=lambda r: r["id"])

dataset = {
    "schema": "decision-gate-expanded-dataset",
    "date": "2026-11-26",
    "source": "origin/master docs/ssot/kanban/cards/*.yml + archive/*.yml",
    "label_rule": {
        "not_ready": list(NEG),
        "ready": "non-empty spec and brief starts with a concrete action verb",
        "excluded": sorted(EXCLUDE),
        "digest_template_cap": 5,
    },
    "counts": {"ready": sum(1 for r in selected if label(r)), "not_ready": sum(1 for r in selected if not label(r))},
    "items": [{"n": i + 1, "id": r["id"], "brief": r["brief"], "label": label(r), "source": r["source"]}
              for i, r in enumerate(selected)],
}
json.dump(dataset, open("/tmp/opencode/decision-gate-expanded-dataset.json", "w"), indent=2)

lines = [f"{i+1}. [{r['id']}] {r['brief']}" for i, r in enumerate(selected)]
questions = {}
for i in range(len(selected)):
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
json.dump(payload, open("/tmp/opencode/decision-gate-expanded-payload.json", "w"), indent=2)
print("dataset", dataset["counts"], "input chars", len(payload["input"]), "questions", len(questions))
for r in selected[:6]:
    print(" ", r["id"], label(r), r["source"])
