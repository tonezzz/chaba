from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional


_CHECKBOX_LINE_RE = re.compile(r"^\s*(?:[-*]\s+)?\[(?P<mark>[xX\s]?)\]\s*(?P<text>.*)\s*$")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ChecklistStep:
    text: str
    done: bool


def normalize_step_text(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    return _WHITESPACE_RE.sub(" ", s)


def parse_checklist_steps(notes_text: str) -> list[ChecklistStep]:
    out: list[ChecklistStep] = []
    for raw_line in str(notes_text or "").splitlines():
        m = _CHECKBOX_LINE_RE.match(raw_line)
        if not m:
            continue

        text = normalize_step_text(m.group("text"))
        if not text:
            continue

        mark = (m.group("mark") or "").strip()
        done = mark.lower() == "x"
        out.append(ChecklistStep(text=text, done=done))

    return out


def next_actionable_step(steps: Iterable[ChecklistStep]) -> Optional[ChecklistStep]:
    for step in steps:
        if not step.done:
            return step
    return None


def infer_strict_template(notes_texts: Iterable[str]) -> Optional[list[str]]:
    counts: dict[tuple[str, ...], int] = {}

    for notes in notes_texts:
        steps = parse_checklist_steps(notes)
        if not steps:
            continue
        if any(not s.done for s in steps):
            continue
        seq = tuple(s.text for s in steps)
        counts[seq] = counts.get(seq, 0) + 1

    best_seq: tuple[str, ...] | None = None
    best_count = 0
    for seq, c in counts.items():
        if c > best_count:
            best_count = c
            best_seq = seq

    if best_seq is None or best_count < 3:
        return None
    return list(best_seq)
