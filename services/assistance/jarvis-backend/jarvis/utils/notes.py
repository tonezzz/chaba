"""
Note extraction utilities.
Pure text processing functions for extracting note content from trigger phrases.
"""
import re
from typing import Optional


# Speech-to-text frequently inserts spaces between Thai words, e.g. "จด บันทึก".
# Also accept common Thai "note" variants.
THAI_NOTE_PATTERNS = (
    r"^(?:ช่วย\s*)?(?:จด\s*บันทึก|สร้าง\s*บันทึก)\s*(?::|\s-\s)?\s*(.*)$",
    r"^(?:ช่วย\s*)?(?:จด\s*โน้ต|สร้าง\s*โน้ต)\s*(?::|\s-\s)?\s*(.*)$",
    r"^(?:ช่วย\s*)?สร้าง\s*เป็น\s*โน้ต\s*(?::|\s-\s)?\s*(.*)$",
)

THAI_TRIGGERS = ("สร้างบันทึก", "จดบันทึก")
ENG_TRIGGERS = ("make a note",)


def extract_note_text(text: str) -> Optional[str]:
    """Extract note text from trigger phrase."""
    raw = str(text or "").strip()
    if not raw:
        return None
    s = " ".join(raw.split())
    lower = s.lower()

    for trig in ENG_TRIGGERS:
        if lower.startswith(trig):
            rest = s[len(trig):].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    for pat in THAI_NOTE_PATTERNS:
        m = re.search(pat, s)
        if m:
            rest = str(m.group(1) or "").strip()
            return rest or None

    for trig in THAI_TRIGGERS:
        if s.startswith(trig):
            rest = s[len(trig):].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    for trig in ENG_TRIGGERS:
        idx = lower.find(trig)
        if idx >= 0:
            rest = s[idx + len(trig):].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    for trig in THAI_TRIGGERS:
        idx = s.find(trig)
        if idx >= 0:
            rest = s[idx + len(trig):].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    return None


def is_note_trigger(text: str) -> bool:
    """Check if text is a note trigger."""
    raw = str(text or "").strip()
    if not raw:
        return False
    s = " ".join(raw.split())
    lower = s.lower()

    if lower.startswith("make a note") or "make a note" in lower:
        return True

    for pat in THAI_NOTE_PATTERNS:
        if re.search(pat, s):
            return True

    for trig in THAI_TRIGGERS:
        if trig in s:
            return True
    return False
