"""Pure tests for collecting and validating offline draft-judge results."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/bench-edu-rejudge.py"
spec = importlib.util.spec_from_file_location("bench_edu_rejudge", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["bench_edu_rejudge"] = mod
spec.loader.exec_module(mod)


class RejudgeHelpers(unittest.TestCase):
    def test_collect_drafts_keeps_question_and_rep(self):
        result = {"tasks": {"clawbot": [{
            "rep": 2,
            "task": "t1",
            "filings": [{"slug": "lesson-x", "topic": "TCP BBR",
                         "content": "<p>A complete saved lesson draft.</p>"}],
        }]}}
        corpus = {"tasks": [{
            "id": "t1",
            "keep": [{"match": ["BBR vs CUBIC", "TCP BBR"]}],
        }]}
        drafts = mod.collect_drafts(result, corpus, "fixture.json")
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["rep"], 2)
        self.assertEqual(drafts[0]["question"], "BBR vs CUBIC")
        self.assertIn("<p>A complete", drafts[0]["html"])

    def test_parse_scores_requires_all_five_valid_axes(self):
        valid = ('{"direct_answer":5,"accuracy":4,"structure":3,'
                 '"hygiene":5,"length":4}')
        scores = mod.parse_scores(valid)
        self.assertEqual(scores["mean"], 4.2)
        self.assertIsNone(mod.parse_scores('{"direct_answer":6}'))
        self.assertIsNone(mod.parse_scores('{"direct_answer":"5"}'))
        self.assertIsNone(mod.parse_scores("not json"))

    def test_summary_ignores_unjudged_rows(self):
        summary = mod.summarize([
            {"lane": "clawbot", "scores": {"mean": 4.0}},
            {"lane": "clawbot", "scores": None},
            {"lane": "clawbot", "scores": {"mean": 3.0}},
        ])
        self.assertEqual(summary["clawbot"], {"n": 2, "mean": 3.5})


if __name__ == "__main__":
    unittest.main()
