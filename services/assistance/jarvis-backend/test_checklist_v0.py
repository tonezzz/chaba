import pytest

from checklist_v0 import (
    ChecklistStep,
    infer_strict_template,
    next_actionable_step,
    normalize_step_text,
    parse_checklist_steps,
)
from tasks_sequential_v0 import (
    SequentialTaskSuggestion,
    suggest_next_step_from_task,
    suggest_template_from_completed_tasks,
)


def test_normalize_step_text_trims_and_collapses_whitespace() -> None:
    assert normalize_step_text("  a   b\t c  ") == "a b c"


@pytest.mark.parametrize(
    "notes,expected",
    [
        ("- [ ] step one\n- [x] step two\n", [ChecklistStep("step one", False), ChecklistStep("step two", True)]),
        ("[] step one\n[x] step two\n", [ChecklistStep("step one", False), ChecklistStep("step two", True)]),
        ("[ ]   step   one\n", [ChecklistStep("step one", False)]),
        ("- [] step one\n", [ChecklistStep("step one", False)]),
        ("- [X] step one\n", [ChecklistStep("step one", True)]),
    ],
)
def test_parse_checklist_steps_accepts_common_syntaxes(notes: str, expected: list[ChecklistStep]) -> None:
    assert parse_checklist_steps(notes) == expected


def test_next_actionable_step_selects_first_incomplete() -> None:
    steps = [
        ChecklistStep("a", True),
        ChecklistStep("b", False),
        ChecklistStep("c", False),
    ]
    assert next_actionable_step(steps) == ChecklistStep("b", False)


def test_next_actionable_step_returns_none_when_all_complete() -> None:
    steps = [ChecklistStep("a", True), ChecklistStep("b", True)]
    assert next_actionable_step(steps) is None


def test_infer_strict_template_requires_3_exact_repeats_of_normalized_sequence() -> None:
    notes1 = "- [x] step  one\n- [x] step two\n"
    notes2 = "[x] step one\n[x] step   two\n"
    notes3 = "- [X] step one\n- [x] step two\n"
    assert infer_strict_template([notes1, notes2, notes3]) == ["step one", "step two"]


def test_infer_strict_template_returns_none_when_fewer_than_3_repeats() -> None:
    notes1 = "- [x] step one\n- [x] step two\n"
    notes2 = "- [x] step one\n- [x] step two\n"
    assert infer_strict_template([notes1, notes2]) is None


def test_infer_strict_template_ignores_incomplete_tasks() -> None:
    complete = "- [x] step one\n- [x] step two\n"
    incomplete = "- [x] step one\n- [ ] step two\n"
    assert infer_strict_template([complete, complete, incomplete, complete]) == ["step one", "step two"]


def test_infer_strict_template_is_strict_about_sequence() -> None:
    a = "- [x] step one\n- [x] step two\n"
    b = "- [x] step two\n- [x] step one\n"
    assert infer_strict_template([a, a, b, a]) == ["step one", "step two"]


def test_suggest_next_step_from_task_uses_notes_checklist() -> None:
    task = {"title": "T", "notes": "- [x] a\n- [ ] b\n- [ ] c\n"}
    assert suggest_next_step_from_task(task) == SequentialTaskSuggestion(next_step_text="b", next_step_index=1)


def test_suggest_next_step_from_task_returns_none_when_no_incomplete_steps() -> None:
    task = {"notes": "- [x] a\n[x] b\n"}
    assert suggest_next_step_from_task(task) == SequentialTaskSuggestion(next_step_text=None, next_step_index=None)


def test_suggest_template_from_completed_tasks_requires_3_repeats() -> None:
    t1 = {"notes": "- [x] step one\n- [x] step two\n"}
    t2 = {"notes": "[x] step one\n[x] step two\n"}
    t3 = {"notes": "- [X] step one\n- [x] step two\n"}
    assert suggest_template_from_completed_tasks([t1, t2, t3]) == ["step one", "step two"]


def test_suggest_template_from_completed_tasks_returns_none_when_fewer_than_3() -> None:
    t1 = {"notes": "- [x] step one\n- [x] step two\n"}
    t2 = {"notes": "- [x] step one\n- [x] step two\n"}
    assert suggest_template_from_completed_tasks([t1, t2]) is None


def test_suggest_template_from_completed_tasks_ignores_incomplete() -> None:
    complete = {"notes": "- [x] a\n- [x] b\n"}
    incomplete = {"notes": "- [x] a\n- [ ] b\n"}
    assert suggest_template_from_completed_tasks([complete, complete, incomplete, complete]) == ["a", "b"]
