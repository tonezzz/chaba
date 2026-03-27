"""
Unit tests for skills_router.

Run with:
    pytest services/assistance/jarvis-backend/test_skills_router.py -v
or:
    python -m pytest services/assistance/jarvis-backend/test_skills_router.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import pytest

from skills_router import (
    HANDLER_ALLOWLIST,
    SkillParseError,
    SkillRow,
    match_skill,
    parse_skill_rows,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(**kw):
    """Build a minimal valid row dict, merging kw overrides."""
    base = {"skill_id": "s1", "pattern": "test", "handler": "search_news"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# HANDLER_ALLOWLIST
# ---------------------------------------------------------------------------


class TestHandlerAllowlist:
    def test_contains_deterministic_tools(self):
        assert "system_skills_list" in HANDLER_ALLOWLIST
        assert "system_skill_get" in HANDLER_ALLOWLIST
        assert "system_skills_bootstrap_queue" in HANDLER_ALLOWLIST

    def test_contains_skill_handlers(self):
        assert "search_news" in HANDLER_ALLOWLIST
        assert "get_gold_price" in HANDLER_ALLOWLIST
        assert "search_web" in HANDLER_ALLOWLIST

    def test_is_frozenset(self):
        assert isinstance(HANDLER_ALLOWLIST, frozenset)


# ---------------------------------------------------------------------------
# parse_skill_rows – basic field parsing
# ---------------------------------------------------------------------------


class TestParseSkillRows:
    def test_minimal_row(self):
        rows = [{"skill_id": "gold", "pattern": "ราคาทอง", "handler": "get_gold_price"}]
        skills = parse_skill_rows(rows)
        assert len(skills) == 1
        s = skills[0]
        assert s.skill_id == "gold"
        assert s.pattern == "ราคาทอง"
        assert s.handler == "get_gold_price"

    def test_defaults(self):
        skills = parse_skill_rows([_row()])
        s = skills[0]
        assert s.enabled is True
        assert s.priority == 0
        assert s.match_type == "contains"
        assert s.lang == "any"
        assert s.arg_json is None

    def test_name_alias_for_skill_id(self):
        rows = [{"name": "news", "pattern": "news", "handler": "search_news"}]
        skills = parse_skill_rows(rows)
        assert len(skills) == 1
        assert skills[0].skill_id == "news"

    def test_skill_id_preferred_over_name(self):
        rows = [{"skill_id": "by_id", "name": "by_name", "pattern": "x", "handler": "search_news"}]
        skills = parse_skill_rows(rows)
        assert skills[0].skill_id == "by_id"

    def test_enabled_string_false(self):
        skills = parse_skill_rows([_row(enabled="false")])
        assert skills[0].enabled is False

    def test_enabled_string_true(self):
        skills = parse_skill_rows([_row(enabled="1")])
        assert skills[0].enabled is True

    def test_enabled_bool_false(self):
        skills = parse_skill_rows([_row(enabled=False)])
        assert skills[0].enabled is False

    def test_priority_int(self):
        skills = parse_skill_rows([_row(priority=7)])
        assert skills[0].priority == 7

    def test_priority_string(self):
        skills = parse_skill_rows([_row(priority="5")])
        assert skills[0].priority == 5

    def test_priority_invalid_defaults_zero(self):
        skills = parse_skill_rows([_row(priority="bad")])
        assert skills[0].priority == 0

    def test_match_type_regex(self):
        skills = parse_skill_rows([_row(match_type="regex", pattern=r"\d+")])
        assert skills[0].match_type == "regex"

    def test_match_type_invalid_defaults_contains(self):
        skills = parse_skill_rows([_row(match_type="fuzzy")])
        assert skills[0].match_type == "contains"

    def test_lang_th(self):
        skills = parse_skill_rows([_row(lang="th")])
        assert skills[0].lang == "th"

    def test_lang_en(self):
        skills = parse_skill_rows([_row(lang="en")])
        assert skills[0].lang == "en"

    def test_lang_any(self):
        skills = parse_skill_rows([_row(lang="any")])
        assert skills[0].lang == "any"

    def test_lang_invalid_defaults_any(self):
        skills = parse_skill_rows([_row(lang="jp")])
        assert skills[0].lang == "any"

    def test_arg_json_dict(self):
        skills = parse_skill_rows([_row(arg_json={"q": "gold"})])
        assert skills[0].arg_json == {"q": "gold"}

    def test_arg_json_string(self):
        skills = parse_skill_rows([_row(arg_json='{"q": "gold"}')])
        assert skills[0].arg_json == {"q": "gold"}

    def test_arg_json_invalid_string_ignored(self):
        skills = parse_skill_rows([_row(arg_json="not-json")])
        assert skills[0].arg_json is None

    def test_returns_list(self):
        result = parse_skill_rows([])
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# parse_skill_rows – rows that are skipped
# ---------------------------------------------------------------------------


class TestParseSkillRowsSkipped:
    def test_skip_missing_skill_id(self):
        rows = [{"pattern": "test", "handler": "search_news"}]
        assert parse_skill_rows(rows) == []

    def test_skip_empty_skill_id(self):
        rows = [{"skill_id": "   ", "pattern": "test", "handler": "search_news"}]
        assert parse_skill_rows(rows) == []

    def test_skip_missing_pattern(self):
        rows = [{"skill_id": "s1", "handler": "search_news"}]
        assert parse_skill_rows(rows) == []

    def test_skip_empty_pattern(self):
        rows = [{"skill_id": "s1", "pattern": "", "handler": "search_news"}]
        assert parse_skill_rows(rows) == []

    def test_skip_missing_handler(self):
        rows = [{"skill_id": "s1", "pattern": "test"}]
        assert parse_skill_rows(rows) == []

    def test_skip_empty_handler(self):
        rows = [{"skill_id": "s1", "pattern": "test", "handler": ""}]
        assert parse_skill_rows(rows) == []


# ---------------------------------------------------------------------------
# parse_skill_rows – handler allowlist enforcement
# ---------------------------------------------------------------------------


class TestHandlerAllowlistEnforcement:
    def test_valid_handler_accepted(self):
        for h in HANDLER_ALLOWLIST:
            skills = parse_skill_rows([_row(handler=h)])
            assert skills[0].handler == h

    def test_unknown_handler_raises(self):
        with pytest.raises(SkillParseError, match="HANDLER_ALLOWLIST"):
            parse_skill_rows([_row(handler="evil_exec")])

    def test_unknown_handler_error_includes_skill_id(self):
        with pytest.raises(SkillParseError, match="my_skill"):
            parse_skill_rows([_row(skill_id="my_skill", handler="rm_rf")])

    def test_unknown_handler_stops_processing(self):
        # Row with bad handler must raise even if earlier row was good
        rows = [
            _row(skill_id="ok", handler="search_news"),
            _row(skill_id="bad", handler="dangerous"),
        ]
        with pytest.raises(SkillParseError):
            parse_skill_rows(rows)


# ---------------------------------------------------------------------------
# match_skill – contains matching
# ---------------------------------------------------------------------------


class TestMatchSkillContains:
    def test_substring_match(self):
        skills = parse_skill_rows([_row(pattern="gold")])
        assert match_skill("gold price today", skills) is not None

    def test_no_match_returns_none(self):
        skills = parse_skill_rows([_row(pattern="gold")])
        assert match_skill("weather forecast", skills) is None

    def test_case_insensitive_pattern_lower(self):
        skills = parse_skill_rows([_row(pattern="gold")])
        assert match_skill("GOLD price", skills) is not None

    def test_case_insensitive_pattern_upper(self):
        skills = parse_skill_rows([_row(pattern="GOLD")])
        assert match_skill("gold price", skills) is not None

    def test_unicode_thai(self):
        skills = parse_skill_rows([_row(pattern="ราคาทอง", handler="get_gold_price")])
        assert match_skill("หาข่าวที่เกี่ยวกับราคาทองคำ", skills) is not None

    def test_empty_skills_returns_none(self):
        assert match_skill("anything", []) is None


# ---------------------------------------------------------------------------
# match_skill – regex matching
# ---------------------------------------------------------------------------


class TestMatchSkillRegex:
    def test_regex_match(self):
        skills = parse_skill_rows(
            [_row(match_type="regex", pattern=r"ราคา(ทอง|เงิน)", handler="get_gold_price")]
        )
        assert match_skill("ราคาทอง", skills) is not None
        assert match_skill("ราคาเงิน", skills) is not None

    def test_regex_no_match(self):
        skills = parse_skill_rows(
            [_row(match_type="regex", pattern=r"ราคา(ทอง|เงิน)", handler="get_gold_price")]
        )
        assert match_skill("ราคาหุ้น", skills) is None

    def test_regex_case_insensitive(self):
        skills = parse_skill_rows(
            [_row(match_type="regex", pattern=r"gold\s*price", handler="get_gold_price")]
        )
        assert match_skill("Gold Price", skills) is not None

    def test_invalid_regex_does_not_raise(self):
        # Bad regex patterns should not crash – they just don't match
        skills = parse_skill_rows([_row(match_type="regex", pattern="[invalid")])
        assert match_skill("anything", skills) is None


# ---------------------------------------------------------------------------
# match_skill – priority ordering
# ---------------------------------------------------------------------------


class TestMatchSkillPriority:
    def test_higher_priority_wins(self):
        rows = [
            _row(skill_id="low", pattern="gold", priority=1, handler="search_news"),
            _row(skill_id="high", pattern="gold", priority=10, handler="get_gold_price"),
        ]
        skills = parse_skill_rows(rows)
        result = match_skill("gold price", skills)
        assert result is not None
        assert result.skill_id == "high"

    def test_zero_vs_negative(self):
        rows = [
            _row(skill_id="zero", pattern="gold", priority=0, handler="search_news"),
            _row(skill_id="neg", pattern="gold", priority=-1, handler="get_gold_price"),
        ]
        skills = parse_skill_rows(rows)
        result = match_skill("gold", skills)
        assert result.skill_id == "zero"

    def test_equal_priority_first_in_list_wins(self):
        rows = [
            _row(skill_id="first", pattern="gold", priority=5, handler="search_news"),
            _row(skill_id="second", pattern="gold", priority=5, handler="get_gold_price"),
        ]
        skills = parse_skill_rows(rows)
        result = match_skill("gold", skills)
        # Stable sort: "first" appears before "second"
        assert result.skill_id == "first"


# ---------------------------------------------------------------------------
# match_skill – language filter
# ---------------------------------------------------------------------------


class TestMatchSkillLang:
    def test_lang_any_matches_any(self):
        skills = parse_skill_rows([_row(lang="any")])
        assert match_skill("test", skills, lang="th") is not None
        assert match_skill("test", skills, lang="en") is not None
        assert match_skill("test", skills, lang="any") is not None

    def test_lang_th_matches_th_only(self):
        skills = parse_skill_rows([_row(lang="th")])
        assert match_skill("test", skills, lang="th") is not None
        assert match_skill("test", skills, lang="en") is None

    def test_lang_en_matches_en_only(self):
        skills = parse_skill_rows([_row(lang="en")])
        assert match_skill("test", skills, lang="en") is not None
        assert match_skill("test", skills, lang="th") is None

    def test_default_lang_is_any(self):
        skills = parse_skill_rows([_row(lang="th")])
        # Default input lang="any" does not satisfy skill lang="th" constraint:
        # _lang_matches("th", "any") is False because "th" != "any" and "th" != "th".
        # Only input lang="th" would match a skill requiring lang="th".
        assert match_skill("test", skills) is None

    def test_lang_any_skill_matches_all_inputs(self):
        skills = parse_skill_rows([_row(lang="any")])
        assert match_skill("test", skills, lang="th") is not None
        assert match_skill("test", skills, lang="en") is not None


# ---------------------------------------------------------------------------
# match_skill – disabled skills
# ---------------------------------------------------------------------------


class TestMatchSkillDisabled:
    def test_disabled_not_matched(self):
        skills = parse_skill_rows([_row(enabled=False)])
        assert match_skill("test message", skills) is None

    def test_disabled_skipped_enabled_matches(self):
        rows = [
            _row(skill_id="off", pattern="test", enabled=False, priority=100, handler="search_news"),
            _row(skill_id="on", pattern="test", enabled=True, priority=1, handler="get_gold_price"),
        ]
        skills = parse_skill_rows(rows)
        result = match_skill("test", skills)
        assert result is not None
        assert result.skill_id == "on"


# ---------------------------------------------------------------------------
# Acceptance criteria – Thai phrase routing (from issue)
# ---------------------------------------------------------------------------


class TestAcceptanceCriteria:
    def test_thai_gold_phrase_routed(self):
        """Acceptance: Thai phrase หาข่าวที่เกี่ยวกับราคาทองคำ routes via skill row."""
        rows = [
            {
                "skill_id": "gold_th",
                "pattern": "ราคาทองคำ",
                "handler": "get_gold_price",
                "lang": "th",
                "priority": 5,
                "enabled": True,
            }
        ]
        skills = parse_skill_rows(rows)
        result = match_skill("หาข่าวที่เกี่ยวกับราคาทองคำ", skills, lang="th")
        assert result is not None
        assert result.skill_id == "gold_th"
        assert result.handler == "get_gold_price"

    def test_routing_disabled_returns_none_for_unloaded_sheet(self):
        """When no skills are loaded (empty sheet), match_skill returns None
        and the caller should fall back to _dispatch_sub_agents."""
        assert match_skill("any text", []) is None

    def test_multiple_skills_correct_priority(self):
        rows = [
            {"skill_id": "news_th", "pattern": "ข่าว", "handler": "search_news", "priority": 3, "lang": "th"},
            {"skill_id": "gold_th", "pattern": "ทองคำ", "handler": "get_gold_price", "priority": 5, "lang": "th"},
        ]
        skills = parse_skill_rows(rows)
        # Text contains both "ข่าว" and "ทองคำ" → gold_th (priority 5) wins
        result = match_skill("ข่าวราคาทองคำ", skills, lang="th")
        assert result.skill_id == "gold_th"
