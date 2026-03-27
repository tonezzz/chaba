from checklist_mutation_v0 import (
    mark_all_checklist_steps_done,
    mark_checklist_step_done,
    mark_checklist_step_done_by_text,
)


def test_mark_checklist_step_done_marks_target_step_by_index() -> None:
    notes = "- [ ] a\n- [ ] b\n- [ ] c\n"
    updated, changed = mark_checklist_step_done(notes, 1)
    assert changed is True
    assert updated == "- [ ] a\n- [x] b\n- [ ] c\n"


def test_mark_checklist_step_done_is_idempotent() -> None:
    notes = "- [x] a\n- [ ] b\n"
    updated, changed = mark_checklist_step_done(notes, 0)
    assert changed is False
    assert updated == notes


def test_mark_checklist_step_done_returns_unchanged_when_index_out_of_range() -> None:
    notes = "- [ ] a\n"
    updated, changed = mark_checklist_step_done(notes, 5)
    assert changed is False
    assert updated == notes


def test_mark_checklist_step_done_preserves_indentation_and_bullet() -> None:
    notes = "  * [ ] a\n"
    updated, changed = mark_checklist_step_done(notes, 0)
    assert changed is True
    assert updated == "  * [x] a\n"


def test_mark_checklist_step_done_by_text_matches_normalized_text() -> None:
    notes = "- [ ]   a   b\n- [ ] c\n"
    updated, changed, idx = mark_checklist_step_done_by_text(notes, "a b")
    assert changed is True
    assert idx == 0
    assert updated == "- [x]   a   b\n- [ ] c\n"


def test_mark_checklist_step_done_by_text_returns_none_when_not_found() -> None:
    notes = "- [ ] a\n"
    updated, changed, idx = mark_checklist_step_done_by_text(notes, "missing")
    assert changed is False
    assert idx is None
    assert updated == notes


def test_mark_all_checklist_steps_done_marks_only_incomplete_steps() -> None:
    notes = "- [ ] a\n- [x] b\n- [ ] c\n"
    updated, changed, count = mark_all_checklist_steps_done(notes)
    assert changed is True
    assert count == 2
    assert updated == "- [x] a\n- [x] b\n- [x] c\n"
