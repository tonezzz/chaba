"""
Skills Sheet routing for jarvis-backend.

This module provides deterministic skill routing driven by a "skills sheet"
(a list of row dicts, e.g. loaded from Google Sheets or a JSON config).

Schema per row
--------------
skill_id   str    Unique identifier. Alias "name" accepted.        Required.
enabled    bool   Whether this row is active.                       Default True.
priority   int    Higher value = matched first.                     Default 0.
match_type str    "contains" (substring) or "regex".               Default "contains".
pattern    str    Substring or regex pattern to match against text. Required.
lang       str    "th" | "en" | "any". Filters by input language.  Default "any".
handler    str    Name from HANDLER_ALLOWLIST.                      Required.
arg_json   dict   Optional extra args forwarded to handler.         Default None.

Usage
-----
    from skills_router import parse_skill_rows, match_skill, HANDLER_ALLOWLIST

    skills = parse_skill_rows(sheet_rows)
    matched = match_skill(user_text, skills, lang="th")
    if matched:
        # call matched.handler with matched.arg_json
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Handler allowlist
# ---------------------------------------------------------------------------

#: Fixed set of handler names that skill rows may reference.
#: Any row referencing a handler outside this set raises SkillParseError.
HANDLER_ALLOWLIST: frozenset = frozenset(
    [
        "answer_question",
        "get_gold_price",
        "get_stock_price",
        "get_weather",
        "play_music",
        "search_news",
        "search_web",
        "set_reminder",
        "system_skill_get",
        "system_skills_bootstrap_queue",
        "system_skills_list",
    ]
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillRow:
    """Immutable, parsed representation of one skills sheet row."""

    skill_id: str
    enabled: bool
    priority: int
    match_type: str  # "contains" | "regex"
    pattern: str
    lang: str  # "th" | "en" | "any"
    handler: str
    arg_json: Optional[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SkillParseError(ValueError):
    """Raised when a skill row contains an invalid value that cannot be
    silently skipped (e.g. an unknown handler not in HANDLER_ALLOWLIST)."""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_bool(val: Any, default: bool = True) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off", ""):
        return False
    return default


def _parse_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _parse_arg_json(val: Any) -> Optional[Dict[str, Any]]:
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str) and val.strip():
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, TypeError):
            pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_skill_rows(rows: Sequence[Dict[str, Any]]) -> List[SkillRow]:
    """Parse raw row dicts (e.g. from Google Sheets JSON export) into
    :class:`SkillRow` objects.

    * Rows missing ``skill_id``/``name``, ``pattern``, or ``handler`` are
      skipped silently.
    * Rows whose ``handler`` is not in :data:`HANDLER_ALLOWLIST` raise
      :exc:`SkillParseError`.
    """
    out: List[SkillRow] = []
    for raw in rows:
        skill_id = str(raw.get("skill_id") or raw.get("name") or "").strip()
        if not skill_id:
            continue

        pattern = str(raw.get("pattern") or "").strip()
        if not pattern:
            continue

        handler = str(raw.get("handler") or "").strip()
        if not handler:
            continue
        if handler not in HANDLER_ALLOWLIST:
            raise SkillParseError(
                f"Skill {skill_id!r}: handler {handler!r} not in HANDLER_ALLOWLIST"
            )

        out.append(
            SkillRow(
                skill_id=skill_id,
                enabled=_parse_bool(raw.get("enabled", True)),
                priority=_parse_int(raw.get("priority"), 0),
                match_type=_coerce_match_type(raw.get("match_type")),
                pattern=pattern,
                lang=_coerce_lang(raw.get("lang")),
                handler=handler,
                arg_json=_parse_arg_json(raw.get("arg_json")),
            )
        )
    return out


def _coerce_match_type(val: Any) -> str:
    s = str(val or "contains").strip().lower()
    return s if s in ("contains", "regex") else "contains"


def _coerce_lang(val: Any) -> str:
    s = str(val or "any").strip().lower()
    return s if s in ("th", "en", "any") else "any"


def _lang_matches(skill_lang: str, text_lang: str) -> bool:
    """Return True when the skill's lang constraint is satisfied."""
    return skill_lang == "any" or skill_lang == text_lang


def _text_matches(skill: SkillRow, text: str) -> bool:
    """Return True when *text* matches *skill*'s pattern."""
    if skill.match_type == "regex":
        try:
            return bool(re.search(skill.pattern, text, re.IGNORECASE | re.UNICODE))
        except re.error:
            return False
    # Default: case-insensitive substring containment
    return skill.pattern.lower() in text.lower()


def match_skill(
    text: str,
    skills: List[SkillRow],
    *,
    lang: str = "any",
) -> Optional[SkillRow]:
    """Return the highest-priority enabled :class:`SkillRow` that matches
    *text* (and optional *lang* hint), or ``None`` if nothing matches.

    Rows are evaluated in descending ``priority`` order so that a row with
    ``priority=10`` is tried before one with ``priority=1``.
    """
    enabled_sorted = sorted(
        (s for s in skills if s.enabled),
        key=lambda s: s.priority,
        reverse=True,
    )
    for skill in enabled_sorted:
        if not _lang_matches(skill.lang, lang):
            continue
        if _text_matches(skill, text):
            return skill
    return None
