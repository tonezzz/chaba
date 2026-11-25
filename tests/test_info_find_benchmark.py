"""Fixtures-only tests for the info-find efficiency benchmark grader."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "info_find_bench", REPO / "evals" / "info-find-efficiency" / "run.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def test_grade_finds_all_facts():
    result = bench.grade("ADA-0031 authorized ada-ocb-skills-wiki-education-2026-11-24",
                         ["ADA-0031", "ada-ocb-skills-wiki-education-2026-11-24"])
    assert result["correct"] and not result["missing"]


def test_grade_reports_missing_fact():
    result = bench.grade("ADA-0031 only", ["ADA-0031", "revid 501"])
    assert not result["correct"]
    assert result["missing"] == ["revid 501"]


def test_decision_adopts_cross_only_when_both_conditions_hold():
    summary = {
        "cross": {"a": {"tokens_est": 500, "correct_rate": 1.0},
                  "b": {"tokens_est": 1000, "correct_rate": 1.0}},
        "narrow": {"a": {"tokens_est": 900, "correct_rate": 1.0},
                   "b": {"tokens_est": 300, "correct_rate": 1.0}},
    }
    d = bench.decide(summary)
    assert d["cross_source_adopt"] and d["narrow_direct_better"]
    assert "cross-source questions only" in d["recommendation"]


def test_decision_refuses_adoption_without_token_gain():
    summary = {
        "cross": {"a": {"tokens_est": 900, "correct_rate": 1.0},
                  "b": {"tokens_est": 1000, "correct_rate": 1.0}},
        "narrow": {"a": {"tokens_est": 900, "correct_rate": 1.0},
                   "b": {"tokens_est": 300, "correct_rate": 1.0}},
    }
    d = bench.decide(summary)
    assert not d["cross_source_adopt"]
    assert "no evidence for cross-source adoption" in d["recommendation"]
