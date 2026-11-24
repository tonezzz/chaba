"""Tests for runner-agent's jev stagnation gate pass (card
jev-stagnation-gate-...-a70f74): gate_pass samples each running
dispatch job's loop state, posts debounced comms on WARN/REPLAN,
counts consecutive HALT verdicts, and only then SIGTERMs the unit —
the finish pass reports it as a failed run naming the gate.
Advisory contract: GATE_ON=0 / no probe module / probe error ->
no-op, never a claim blocker."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent_gate",
                                                  SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["runner_agent_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeLG:
    """Stand-in for scripts/jev/loop-gate.py."""
    verdict = {"verdict": "continue", "noul": {"p": 0.1},
               "choice": {"action": "continue"},
               "backends": {"noul": "fake", "choice": "fake"},
               "degraded": []}
    calls = []
    raises = False

    @classmethod
    def reset(cls, verdict=None):
        cls.verdict = verdict or {"verdict": "continue",
                                  "noul": {"p": 0.1},
                                  "choice": {"action": "continue"},
                                  "backends": {}, "degraded": []}
        cls.calls = []
        cls.raises = False

    @staticmethod
    def normalize_state(d):
        return d

    @staticmethod
    def state_from_taskdir(td, task=""):
        return {"loop": "agent", "task": task, "iterations": 3,
                "elapsed_s": 4000, "heartbeat_age_s": 30,
                "recent": ["still working"], "signals": {}}

    @classmethod
    def gate(cls, state, halt_p=None, warn_p=None):
        cls.calls.append(state)
        if cls.raises:
            raise RuntimeError("backend exploded")
        return cls.verdict


def _halt(p=0.9):
    return {"verdict": "halt", "noul": {"p": p},
            "choice": {"action": "halt", "confidence": 0.8},
            "backends": {"noul": "jevos", "choice": "jevos"},
            "degraded": []}


def _warn(p=0.6):
    return {"verdict": "warn", "noul": {"p": p},
            "choice": {"action": "warn"},
            "backends": {"noul": "jevos", "choice": "jevos"},
            "degraded": []}


class GatePassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self.m = m
        self._saved = (m.GATE_ON, m.GATE_MIN_AGE_S, m.GATE_INTERVAL_S,
                       m.GATE_HALT_STRIKES, m.GATE_TYPES,
                       m.lg_module, m.unit_active, m.api, m._signal_job,
                       m._notify, m._job_taskdir)
        m.GATE_ON = "auto"
        m.GATE_MIN_AGE_S = 0
        m.GATE_INTERVAL_S = 0
        m.GATE_HALT_STRIKES = 2
        m.GATE_TYPES = {"dispatch"}
        m.lg_module = lambda: _FakeLG
        m.unit_active = lambda u: True
        self._tmpdir = tempfile.TemporaryDirectory()
        m._job_taskdir = lambda ent: Path(self._tmpdir.name)
        self.posts = []
        self.signals = []
        m.api = lambda path, body=None: (
            self.posts.append((path, body)) or {})
        m._signal_job = lambda unit, sig: self.signals.append((unit, sig))
        m._notify = lambda *a, **k: None
        _FakeLG.reset()

    def tearDown(self):
        (self.m.GATE_ON, self.m.GATE_MIN_AGE_S, self.m.GATE_INTERVAL_S,
         self.m.GATE_HALT_STRIKES, self.m.GATE_TYPES,
         self.m.lg_module, self.m.unit_active, self.m.api,
         self.m._signal_job, self.m._notify,
         self.m._job_taskdir) = self._saved
        self._tmpdir.cleanup()

    def _state(self):
        return {"c1": {"unit": "devin-task-x", "type": "dispatch",
                       "tid": "t1", "at": time.time() - 4000}}

    def _comments(self):
        return [b.get("text", "") for p, b in self.posts
                if p == "/comment"]

    def test_disabled_is_noop(self):
        self.m.GATE_ON = "0"
        st = self._state()
        self.assertFalse(self.m.gate_pass(st))
        self.assertEqual(_FakeLG.calls, [])

    def test_no_module_is_noop(self):
        self.m.lg_module = lambda: None
        self.assertFalse(self.m.gate_pass(self._state()))
        self.assertEqual(self.signals, [])

    def test_probe_error_never_blocks(self):
        _FakeLG.raises = True
        st = self._state()
        self.assertFalse(self.m.gate_pass(st))
        self.assertEqual(self.signals, [])
        self.assertEqual(self._comments(), [])

    def test_inactive_unit_skipped(self):
        self.m.unit_active = lambda u: False
        self.assertFalse(self.m.gate_pass(self._state()))
        self.assertEqual(_FakeLG.calls, [])

    def test_wrong_type_skipped(self):
        st = {"c1": {"unit": "u", "type": "script", "at": 0}}
        self.assertFalse(self.m.gate_pass(st))
        self.assertEqual(_FakeLG.calls, [])

    def test_too_young_skipped(self):
        self.m.GATE_MIN_AGE_S = 99999
        self.assertFalse(self.m.gate_pass(self._state()))
        self.assertEqual(_FakeLG.calls, [])

    def test_continue_is_quiet(self):
        st = self._state()
        self.assertFalse(self.m.gate_pass(st))
        self.assertEqual(self._comments(), [])
        self.assertEqual(self.signals, [])
        self.assertEqual(st["c1"]["gate"]["verdict"], "continue")

    def test_warn_posts_once_then_quiet(self):
        _FakeLG.verdict = _warn()
        st = self._state()
        self.m.gate_pass(st)
        self.m.gate_pass(st)   # interval=0 -> re-probes
        warns = [c for c in self._comments() if "warn" in c]
        self.assertEqual(len(warns), 1)
        self.assertEqual(self.signals, [])

    def test_halt_needs_strikes_then_kills(self):
        _FakeLG.verdict = _halt()
        st = self._state()
        self.m.gate_pass(st)          # streak 1 — watch note only
        self.assertEqual(self.signals, [])
        self.assertTrue(any("1/2" in c for c in self._comments()))
        self.m.gate_pass(st)          # streak 2 — SIGTERM
        self.assertEqual(self.signals, [("devin-task-x", "TERM")])
        self.assertTrue(st["c1"].get("gate_halt"))
        self.assertTrue(any("HALT" in c for c in self._comments()))
        # a third pass must not re-kill or re-comment
        n_comments = len(self._comments())
        self.m.gate_pass(st)
        self.assertEqual(len(self.signals), 1)
        self.assertEqual(len(self._comments()), n_comments)

    def test_non_halt_resets_streak(self):
        _FakeLG.verdict = _halt()
        st = self._state()
        self.m.gate_pass(st)                    # streak 1
        _FakeLG.verdict = {"verdict": "continue", "noul": {"p": 0.1},
                           "choice": {"action": "continue"},
                           "backends": {}, "degraded": []}
        self.m.gate_pass(st)                    # reset
        _FakeLG.verdict = _halt()
        self.m.gate_pass(st)                    # streak 1 again
        self.assertEqual(self.signals, [])
        self.assertEqual(st["c1"]["gate"]["halt_streak"], 1)

    def test_unknown_verdict_is_continue_like(self):
        _FakeLG.verdict = {"verdict": "unknown", "noul": {"p": None},
                           "choice": {"action": None},
                           "backends": {}, "degraded": ["all down"]}
        st = self._state()
        self.m.gate_pass(st)
        self.assertEqual(self._comments(), [])
        self.assertEqual(self.signals, [])


if __name__ == "__main__":
    unittest.main()
