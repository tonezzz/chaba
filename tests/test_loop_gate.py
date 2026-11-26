"""Tests for scripts/jev/loop-gate.py — the Jev stagnation probe
(card jev-stagnation-gate-...-a70f74): verdict = max severity of the
noul p and the choice action; degradation is data; the gate never
kills on missing data (unknown -> callers treat as continue)."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "jev"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "loop_gate", REPO / "scripts" / "jev" / "loop-gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["loop_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


class NormalizeStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lg = _load()

    def test_defaults_and_passthrough(self):
        st = self.lg.normalize_state({"task": "x", "custom": 1})
        self.assertEqual(st["loop"], "agent")
        self.assertEqual(st["iterations"], 0)
        self.assertIsNone(st["heartbeat_age_s"])
        self.assertEqual(st["custom"], 1)
        self.assertEqual(st["recent"], [])

    def test_recent_string_and_truncation(self):
        st = self.lg.normalize_state(
            {"recent": "one line"})
        self.assertEqual(st["recent"], ["one line"])
        st = self.lg.normalize_state(
            {"recent": [f"line-{i}-" + "x" * 500 for i in range(30)]})
        self.assertEqual(len(st["recent"]), self.lg.MAX_RECENT)
        self.assertEqual(st["recent"][-1][:9], "line-29-x")
        for line in st["recent"]:
            self.assertLessEqual(len(line), self.lg.MAX_LINE)

    def test_non_dict_is_empty(self):
        self.assertEqual(self.lg.normalize_state("junk"), {})
        self.assertEqual(self.lg.normalize_state(None), {})


class QuestionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lg = _load()

    def test_two_questions_with_verdict_criteria(self):
        q = self.lg.build_questions()
        self.assertEqual(q["stagnant"]["type"], "noul")
        self.assertEqual(q["action"]["type"], "choice")
        for v in ("continue", "warn", "replan", "halt"):
            self.assertIn(v, q["action"]["criteria"])
        self.assertIn("true", q["stagnant"]["criteria"])
        self.assertIn("false", q["stagnant"]["criteria"])


class ChoiceStubTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lg = _load()

    def test_student_stub_detected(self):
        self.assertTrue(self.lg._is_choice_stub(
            {"choice": "answer", "confidence": 0.0}))
        self.assertFalse(self.lg._is_choice_stub(
            {"choice": "halt", "confidence": 0.486}))
        self.assertFalse(self.lg._is_choice_stub(
            {"choice": "answer", "confidence": 0.9}))
        self.assertFalse(self.lg._is_choice_stub({}))
        self.assertFalse(self.lg._is_choice_stub(None))


class NoulLevelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lg = _load()

    def test_thresholds(self):
        f = self.lg._noul_level
        self.assertIsNone(f(None))
        self.assertEqual(f(0.9), self.lg.LEVEL["halt"])
        self.assertEqual(f(0.7), self.lg.LEVEL["halt"])
        self.assertEqual(f(0.6), self.lg.LEVEL["warn"])
        self.assertEqual(f(0.5), self.lg.LEVEL["warn"])
        self.assertEqual(f(0.1), self.lg.LEVEL["continue"])


class GateVerdictTest(unittest.TestCase):
    """gate() verdict = max(noul level, choice level); unknown only
    when BOTH signals are absent."""

    @classmethod
    def setUpClass(cls):
        cls.lg = _load()

    def setUp(self):
        self.lg = self.__class__.lg
        self._saved = (self.lg._ask_noul, self.lg._ask_choice)

    def tearDown(self):
        self.lg._ask_noul, self.lg._ask_choice = self._saved

    def _gate(self, p, act, conf=0.9, degraded=None):
        self.lg._ask_noul = lambda s, q, d: (
            (d.extend(degraded or []), (p, "stub-noul", 1))[1])
        self.lg._ask_choice = lambda s, q, d: (
            (d.extend(degraded or []), (act, conf, "stub-choice", 1))[1])
        return self.lg.gate({"task": "t", "recent": ["r"]})

    def test_noul_halt_alone(self):
        v = self._gate(0.9, "continue")
        self.assertEqual(v["verdict"], "halt")
        self.assertEqual(v["backends"], {"noul": "stub-noul",
                                       "choice": "stub-choice"})

    def test_choice_halt_alone(self):
        v = self._gate(0.1, "halt")
        self.assertEqual(v["verdict"], "halt")

    def test_choice_beats_low_noul(self):
        v = self._gate(0.2, "replan")
        self.assertEqual(v["verdict"], "replan")

    def test_warn_from_either_signal(self):
        self.assertEqual(self._gate(0.6, "continue")["verdict"], "warn")
        self.assertEqual(self._gate(0.1, "warn")["verdict"], "warn")

    def test_continue(self):
        v = self._gate(0.05, "continue", conf=0.9)
        self.assertEqual(v["verdict"], "continue")
        self.assertEqual(v["noul"]["level"], "continue")

    def test_unknown_when_no_signal(self):
        v = self._gate(None, None)
        self.assertEqual(v["verdict"], "unknown")

    def test_choice_absent_noul_still_decides(self):
        v = self._gate(0.8, None)
        self.assertEqual(v["verdict"], "halt")
        v = self._gate(0.1, None)
        self.assertEqual(v["verdict"], "continue")

    def test_degraded_is_data(self):
        v = self._gate(0.1, "continue",
                       degraded=["jevos: connection refused"])
        self.assertIn("jevos: connection refused", v["degraded"])

    def test_thresholds_override(self):
        self.lg._ask_noul = lambda s, q, d: (0.6, "n", 1)
        self.lg._ask_choice = lambda s, q, d: (None, None, None, 1)
        v = self.lg.gate({"recent": ["x"]}, halt_p=0.5, warn_p=0.4)
        self.assertEqual(v["verdict"], "halt")
        self.assertEqual(v["thresholds"], {"halt_p": 0.5, "warn_p": 0.4})

    def test_gate_normalizes_state(self):
        seen = {}
        self.lg._ask_noul = lambda s, q, d: (seen.setdefault("s", s),
                                             (0.1, "n", 1))[1]
        self.lg._ask_choice = lambda s, q, d: (None, None, None, 1)
        self.lg.gate({"recent": "x" * 500})
        self.assertLessEqual(len(seen["s"]["recent"][0]), self.lg.MAX_LINE)


class TaskdirStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lg = _load()

    def test_empty_dir_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(self.lg.state_from_taskdir(td))

    def test_missing_dir_returns_none(self):
        self.assertIsNone(self.lg.state_from_taskdir("/no/such/dir"))

    def test_builds_state_from_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "meta.json").write_text(json.dumps(
                {"card": "test-card",
                 "started_at": time.strftime(
                     "%Y-%m-%dT%H:%M:%S+00:00",
                     time.gmtime(time.time() - 600))}))
            (p / "run.1.log").write_text(
                "line one\nline two\n" + "err=HTTP 429\n" * 5)
            (p / "events.jsonl").write_text('{"a":1}\n{"a":2}\n')
            st = self.lg.state_from_taskdir(td, now=time.time())
            self.assertIsNotNone(st)
            self.assertEqual(st["task"], "test-card")
            self.assertEqual(st["iterations"], 2)   # events rows
            self.assertIn("heartbeat_age_s", st)
            self.assertGreaterEqual(st["heartbeat_age_s"], 0)
            self.assertTrue(st["recent"])
            self.assertIn("err=HTTP 429", st["recent"][-1])
            self.assertGreater(st["elapsed_s"], 500)

    def test_transcript_steps_win_iterations(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "run.1.log").write_text("working\n")
            (p / "transcript.json").write_text(json.dumps(
                {"steps": [{}, {}, {}, {}]}))
            st = self.lg.state_from_taskdir(td)
            self.assertEqual(st["iterations"], 4)
            self.assertTrue(st["signals"]["exit_code"] is False)


class BackendsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lg = _load()

    def test_jev_api_skipped_without_key(self):
        saved = self.lg.JEV_API_KEY
        try:
            self.lg.JEV_API_KEY = ""
            names = [n for n, _, _ in self.lg._backends(
                ["jev-api", "jev-student", "jevos"])]
            self.assertNotIn("jev-api", names)
            self.assertEqual(names, ["jev-student", "jevos"])
        finally:
            self.lg.JEV_API_KEY = saved

    def test_order_honored_and_unknown_dropped(self):
        names = [n for n, _, _ in self.lg._backends(
            ["bogus", "jevos", "jev-student"])]
        self.assertEqual(names, ["jevos", "jev-student"])


if __name__ == "__main__":
    unittest.main()
