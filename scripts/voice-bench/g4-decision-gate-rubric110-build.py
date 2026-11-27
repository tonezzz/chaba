#!/usr/bin/env python3
"""Cross-check the rubric choice arm on the earlier independent 110-brief holdout.

Reuses the exact score/choice criteria from rubric130 and the exact shared input
from the original 110-brief Decisions call, so fixed-threshold performance can
be compared on a second disjoint set rather than one validation set alone.
"""
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
BASE = json.load(open(RESULTS / "g4-decision-gate-heldout110-payload.json"))
DS = json.load(open(RESULTS / "g4-decision-gate-heldout110-dataset.json"))
RUB = json.load(open(RESULTS / "g4-decision-gate-rubric130-payload.json"))
LEVELS = RUB["questions"]["score_1"]["criteria"]
CHOICES = RUB["questions"]["choice_1"]["criteria"]

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
out = RESULTS / "g4-decision-gate-rubric110-payload.json"
json.dump(payload, open(out, "w"), indent=2)
print("briefs", len(DS["items"]), "questions", len(questions),
      "input chars", len(payload["input"]), "payload bytes", out.stat().st_size)
