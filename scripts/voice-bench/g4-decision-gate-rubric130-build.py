#!/usr/bin/env python3
"""Build a Decisions API rubric probe over the same 130 validation briefs.

Two question types per brief, over the identical shared input used by the
binary noul run, so the arms are directly comparable:

  score_N  -> ordered 4-level dispatch-readiness rubric (expected level 0-3)
  choice_N -> single disposition from ready / deferral / approval_gated /
              fixture_or_status, with calibrated per-option probabilities

Docs followed: https://aistudio.google.com/docs/decisions-api.md and
https://aistudio.google.com/docs/models/gemini-decision-1.md (fetched before
writing this script). Zero output tokens, v1beta REST, free key on idc03.
"""
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
BASE = json.load(open(RESULTS / "g4-decision-gate-validation130-payload.json"))
DS = json.load(open(RESULTS / "g4-decision-gate-validation130-dataset.json"))

LEVELS = [
    "Not dispatchable: the brief explicitly defers to a note or another source, says no action is needed, or is only a fixture or umbrella card.",
    "Gated: a concrete action exists, but the brief defers to human approval or a later decision before work can start.",
    "Partial: a concrete action and target are named, but a key detail depends on another source (for example 'details in the note').",
    "Fully ready: a concrete action and target are stated in the brief with enough detail to dispatch now, without consulting another source.",
]
CHOICES = {
    "ready": "A concrete action and target are stated with enough detail to dispatch now.",
    "deferral": "The brief defers the actual action to a note or another source, or says no action is needed.",
    "approval_gated": "A concrete action exists but is gated on a person's approval or a later decision.",
    "fixture_or_status": "A test fixture, umbrella card, or descriptive status with no dispatchable task.",
}

questions = {}
for it in DS["items"]:
    n = it["n"]
    questions[f"score_{n}"] = {
        "type": "score",
        "instructions": (
            f"Brief {n}: rate how ready this kanban brief is for immediate dispatch. "
            "Judge only what the brief itself says, not any card metadata or notes."
        ),
        "criteria": LEVELS,
    }
    questions[f"choice_{n}"] = {
        "type": "choice",
        "instructions": (
            f"Brief {n}: which single disposition best describes this kanban brief? "
            "Judge only what the brief itself says, not any card metadata or notes."
        ),
        "criteria": CHOICES,
    }

payload = {"model": "gemini-decision-1", "input": BASE["input"], "questions": questions}
out = RESULTS / "g4-decision-gate-rubric130-payload.json"
json.dump(payload, open(out, "w"), indent=2)
print("briefs", len(DS["items"]), "questions", len(questions),
      "input chars", len(payload["input"]), "payload bytes", out.stat().st_size)
