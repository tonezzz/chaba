#!/usr/bin/env python3
"""Build a choice-arm probe over the same 60 diverse-negative briefs.

The shared input is copied verbatim from the binary noul payload, so the two
arms are directly paired. Only choice_N questions are emitted (no score arm).

No API calls; emits payload for one batched Decisions call.
"""
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
BASE = json.load(open(RESULTS / "g4-decision-gate-diverse60-payload.json"))
DS = json.load(open(RESULTS / "g4-decision-gate-diverse60-dataset.json"))

CHOICES = {
    "ready": "A concrete action and target are stated with enough detail to dispatch now.",
    "deferral": "The brief defers the actual action to a note or another source, or says no action is needed.",
    "approval_gated": "A concrete action exists but is gated on a person's approval or a later decision.",
    "fixture_or_status": "A test fixture, umbrella card, or descriptive status with no dispatchable task.",
}

questions = {}
for it in DS["items"]:
    n = it["n"]
    questions[f"choice_{n}"] = {
        "type": "choice",
        "instructions": (
            f"Brief {n}: which single disposition best describes this kanban brief? "
            "Judge only what the brief itself says, not any card metadata or notes."
        ),
        "criteria": CHOICES,
    }

payload = {"model": "gemini-decision-1", "input": BASE["input"], "questions": questions}
out = RESULTS / "g4-decision-gate-diverse60-choice-payload.json"
json.dump(payload, open(out, "w"), indent=2)
print("briefs", len(DS["items"]), "questions", len(questions),
      "input chars", len(payload["input"]), "payload bytes", out.stat().st_size)
