"""Tests for scripts/litellm/budget-watch.py — the LiteLLM key
budget monitor added for model-key-usage-control (SEC-0962)."""

import importlib.util
from pathlib import Path
import unittest


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "budget_watch", REPO / "scripts/litellm/budget-watch.py")
bw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bw)


def _row(alias, cap, spend, dur="30d", reset="2026-11-01", models="{}"):
    return {"key_alias": alias, "max_budget": cap,
            "budget_duration": dur, "spend": spend,
            "budget_reset_at": reset, "models": models}


class JudgeTest(unittest.TestCase):
    def test_over_cap_alerts(self):
        j = bw.judge(_row("bench", 2.0, 2.0084))
        self.assertEqual(j["level"], "alert")
        self.assertIn("bench", j["why"])

    def test_at_cap_alerts(self):
        self.assertEqual(
            bw.judge(_row("x", 5.0, 5.0))["level"], "alert")

    def test_near_cap_warns(self):
        self.assertEqual(
            bw.judge(_row("chaba", 20.0, 19.72))["level"], "warn")

    def test_warn_threshold_boundary(self):
        # WARN_PCT default 80 — exactly 80% warns.
        self.assertEqual(
            bw.judge(_row("x", 10.0, 8.0))["level"], "warn")
        self.assertEqual(
            bw.judge(_row("x", 10.0, 7.99))["level"], "ok")

    def test_under_cap_ok(self):
        self.assertEqual(
            bw.judge(_row("ada", 30.0, 14.53))["level"], "ok")

    def test_uncapped_is_note(self):
        j = bw.judge(_row("free", None, 3.0))
        self.assertEqual(j["level"], "note")
        self.assertIsNone(j["pct"])

    def test_pct_math(self):
        self.assertAlmostEqual(
            bw.judge(_row("k", 20.0, 19.672))["pct"], 98.36, places=1)


class ReportTest(unittest.TestCase):
    def test_verdict_rollup(self):
        rows = [
            _row("a", 10.0, 1.0),      # ok
            _row("b", 10.0, 9.0),      # warn
            _row("c", 2.0, 2.01),      # alert
            _row("d", None, 0.5),      # note
        ]
        rep = bw.report(rows)
        self.assertEqual(rep["verdict"], "alert")
        self.assertEqual(rep["alerts"], 1)
        self.assertEqual(rep["warns"], 1)

    def test_verdict_warn_when_no_alerts(self):
        rep = bw.report([_row("a", 10.0, 9.0)])
        self.assertEqual(rep["verdict"], "warn")

    def test_verdict_ok(self):
        rep = bw.report([_row("a", 10.0, 1.0), _row("b", None, 0.0)])
        self.assertEqual(rep["verdict"], "ok")

    def test_format_line_lists_findings(self):
        rep = bw.report([_row("bench", 2.0, 2.01),
                         _row("ada", 30.0, 1.0)])
        text = bw.format_line(rep)
        self.assertIn("bench", text)
        self.assertNotIn("$1.0", text)

    def test_card_id_slug(self):
        self.assertEqual(bw.card_id("LITELLM_KEY_CHABA"),
                         "budget-watch-litellm-key-chaba")


class ParseTest(unittest.TestCase):
    def test_psql_row_parsing_via_fixture(self):
        # judge() input shape == what rows_via_psql emits.
        rep = bw.report(bw.SELFTEST_ROWS)
        by = {f["key_alias"]: f for f in rep["findings"]}
        self.assertEqual(by["bench"]["level"], "alert")
        self.assertEqual(by["chaba"]["level"], "warn")
        self.assertEqual(by["uncapped-test"]["level"], "note")


if __name__ == "__main__":
    unittest.main()
