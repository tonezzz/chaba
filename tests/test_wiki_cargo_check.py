"""Fixtures-only verifier for scripts/wiki-cargo-check.py (OPS-0038)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wiki_cargo_check", REPO / "scripts" / "wiki-cargo-check.py")
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


def test_table_and_topic_present():
    result = checker.check(
        {"cargotables": [{"name": "Education"}]},
        {"cargoquery": [{"title": {"_pageName": "Education:Ada-Ocb-Skills",
                                   "topic": "ada-ocb-skills",
                                   "next_review": "2026-12-08"}}]})
    assert result["ok"] is True
    assert result["table_present"] and result["topic_found"]
    assert result["rows"] == 1 and not result["reasons"]


def test_missing_table_fails_with_reason():
    result = checker.check({"cargotables": []}, {"cargoquery": []})
    assert result["ok"] is False
    assert result["table_present"] is False
    assert any("missing" in reason for reason in result["reasons"])


def test_table_present_but_topic_missing_fails():
    result = checker.check(
        {"cargotables": ["Education"]},
        {"cargoquery": [{"title": {"topic": "other"}}]})
    assert result["ok"] is False
    assert result["table_present"] is True
    assert result["topic_found"] is False


def test_live_shape_without_table_still_reports_cleanly():
    # The current wiki returns an empty cargotables list; the verifier must
    # report that as a normal failure, not an exception.
    result = checker.check({"cargotables": []}, {"cargoquery": []})
    assert result["tables_seen"] == []
    assert result["reasons"] == [
        "table 'Education' missing from action=cargotables (found: [])",
        "topic 'ada-ocb-skills' not found in cargoquery rows",
    ]
