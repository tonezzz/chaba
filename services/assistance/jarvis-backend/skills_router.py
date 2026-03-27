"""Deterministic skills-sheet routing for jarvis-backend.

Skills are matched by regex patterns (Thai + English). When
``system.skills.routing.enabled`` (env ``SKILLS_ROUTING_ENABLED``) is true,
an incoming text is checked against SKILL_PATTERNS and the first match wins.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Skills Sheet SSOT – pattern → skill_name
# Add more rows here to extend the skill set.
# ---------------------------------------------------------------------------
SKILL_PATTERNS: List[Tuple[str, str]] = [
    # Thai patterns for news search
    (r"หาข่าว", "news_search"),
    (r"ค้นข่าว", "news_search"),
    (r"ข่าวเกี่ยวกับ", "news_search"),
    (r"ข่าวล่าสุดเกี่ยวกับ", "news_search"),
    # English fall-through
    (r"\bfind\s+news\b", "news_search"),
    (r"\bsearch\s+news\b", "news_search"),
    (r"\bnews\s+about\b", "news_search"),
]


def is_routing_enabled() -> bool:
    """Return True when the skills routing gate is on."""
    return os.getenv("SKILLS_ROUTING_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def route(text: str) -> Optional[str]:
    """Return the matching skill name, or ``None`` if routing is disabled or no match.

    Args:
        text: Raw voice transcript or user message.

    Returns:
        Skill name string (e.g. ``"news_search"``) or ``None``.
    """
    if not is_routing_enabled():
        return None
    normalized = (text or "").strip()
    for pattern, skill in SKILL_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return skill
    return None
