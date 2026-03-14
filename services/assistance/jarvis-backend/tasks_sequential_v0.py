from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from checklist_v0 import ChecklistStep, infer_strict_template, next_actionable_step, parse_checklist_steps


@dataclass(frozen=True)
class SequentialTaskSuggestion:
    next_step_text: Optional[str]
    next_step_index: Optional[int]


def suggest_next_step_from_task(task: dict[str, Any]) -> SequentialTaskSuggestion:
    notes = task.get("notes")
    notes_text = str(notes or "")

    steps = parse_checklist_steps(notes_text)
    next_step = next_actionable_step(steps)
    if next_step is None:
        return SequentialTaskSuggestion(next_step_text=None, next_step_index=None)

    idx = _index_of_step(steps, next_step)
    return SequentialTaskSuggestion(next_step_text=next_step.text, next_step_index=idx)


def suggest_template_from_completed_tasks(tasks: list[dict[str, Any]]) -> Optional[list[str]]:
    notes_texts: list[str] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        notes_texts.append(str(t.get("notes") or ""))

    return infer_strict_template(notes_texts)


def _index_of_step(steps: list[ChecklistStep], target: ChecklistStep) -> int:
    for i, s in enumerate(steps):
        if s == target:
            return i
    return -1
