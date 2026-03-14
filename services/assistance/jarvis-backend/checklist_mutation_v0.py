from __future__ import annotations

import re

from checklist_v0 import normalize_step_text


_CHECKBOX_MUT_RE = re.compile(
    r"^(?P<indent>\s*)(?P<bullet>(?:[-*]\s+)?)\[(?P<mark>[xX\s]?)\](?P<after>\s*.*)$"
)


def mark_checklist_step_done(notes_text: str, step_index: int) -> tuple[str, bool]:
    if step_index is None or int(step_index) < 0:
        return str(notes_text or ""), False

    idx_target = int(step_index)
    lines = str(notes_text or "").splitlines(keepends=True)

    found_step_idx = -1
    changed = False
    out_lines: list[str] = []

    for raw_line in lines:
        m = _CHECKBOX_MUT_RE.match(raw_line.rstrip("\n"))
        if not m:
            out_lines.append(raw_line)
            continue

        found_step_idx += 1
        if found_step_idx != idx_target:
            out_lines.append(raw_line)
            continue

        indent = m.group("indent")
        bullet = m.group("bullet")
        mark = (m.group("mark") or "").strip()
        after = m.group("after")

        if mark.lower() == "x":
            out_lines.append(raw_line)
            continue

        newline = "\n" if raw_line.endswith("\n") else ""
        out_lines.append(f"{indent}{bullet}[x]{after}{newline}")
        changed = True

    return "".join(out_lines), changed


def find_checklist_step_indices_by_text(notes_text: str, step_text: str) -> list[int]:
    target = normalize_step_text(step_text)
    if not target:
        return []

    indices: list[int] = []
    step_idx = -1

    for raw_line in str(notes_text or "").splitlines():
        m = _CHECKBOX_MUT_RE.match(raw_line)
        if not m:
            continue
        step_idx += 1
        after = m.group("after")
        current_text = normalize_step_text(after)
        if current_text == target:
            indices.append(step_idx)

    return indices


def mark_checklist_step_done_by_text(notes_text: str, step_text: str) -> tuple[str, bool, int | None]:
    target = normalize_step_text(step_text)
    if not target:
        return str(notes_text or ""), False, None

    lines = str(notes_text or "").splitlines(keepends=True)
    step_idx = -1
    matched_idx: int | None = None
    changed = False
    out_lines: list[str] = []

    for raw_line in lines:
        m = _CHECKBOX_MUT_RE.match(raw_line.rstrip("\n"))
        if not m:
            out_lines.append(raw_line)
            continue

        step_idx += 1
        after = m.group("after")
        current_text = normalize_step_text(after)
        if current_text != target or matched_idx is not None:
            out_lines.append(raw_line)
            continue

        matched_idx = step_idx
        indent = m.group("indent")
        bullet = m.group("bullet")
        mark = (m.group("mark") or "").strip()

        if mark.lower() == "x":
            out_lines.append(raw_line)
            continue

        newline = "\n" if raw_line.endswith("\n") else ""
        out_lines.append(f"{indent}{bullet}[x]{after}{newline}")
        changed = True

    return "".join(out_lines), changed, matched_idx


def mark_all_checklist_steps_done(notes_text: str) -> tuple[str, bool, int]:
    lines = str(notes_text or "").splitlines(keepends=True)
    changed_any = False
    changed_count = 0
    out_lines: list[str] = []

    for raw_line in lines:
        m = _CHECKBOX_MUT_RE.match(raw_line.rstrip("\n"))
        if not m:
            out_lines.append(raw_line)
            continue

        indent = m.group("indent")
        bullet = m.group("bullet")
        mark = (m.group("mark") or "").strip()
        after = m.group("after")

        if mark.lower() == "x":
            out_lines.append(raw_line)
            continue

        newline = "\n" if raw_line.endswith("\n") else ""
        out_lines.append(f"{indent}{bullet}[x]{after}{newline}")
        changed_any = True
        changed_count += 1

    return "".join(out_lines), changed_any, changed_count
