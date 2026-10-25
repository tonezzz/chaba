"""Regression tests for the dispatch-lane branch of runner-agent.start_task.

OPS-0846 review (2026-10-25): `lane` was only bound inside the
`if not a.get("lane")` classify block, so any card that already carried
action.lane — an explicit lane, or one persisted by the JEV_LANE
claim-classify — hit `if lane in LANE_MODELS` unbound and crashed the
claim with UnboundLocalError (card stayed claimed, no unit started).
"""

from __future__ import annotations

import importlib.util
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _card(**action_kw):
    a = {"type": "dispatch", "status": "queued", "repo": "chaba"}
    a.update(action_kw)
    return {"id": "lane-card", "title": "lane test", "spec": "do a thing",
            "action": a}


class StartTaskLaneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in
                       ("OPENCODE_LANES", "DISPATCH", "HOST")}
        self._saved_fn = {k: getattr(m, k) for k in
                          ("sh", "classify_lane", "start_opencode_lane",
                           "dr_module", "enforce_task_limits")}
        m.DISPATCH = str(SCRIPT)          # exists -> dispatch executor present
        m.dr_module = lambda: None        # no host checkout resolution
        m.enforce_task_limits = lambda *a, **k: None
        self.calls = []
        m.sh = lambda argv, **kw: self.calls.append(argv) or _proc(
            0, "fake-tid-123\n")

    def tearDown(self):
        m = self.mod
        for k, v in self._saved.items():
            setattr(m, k, v)
        for k, v in self._saved_fn.items():
            setattr(m, k, v)

    def test_explicit_lane_devin_path_does_not_crash(self):
        """Card with action.lane already set + OPENCODE_LANES=0 must
        dispatch through devin-dispatch, not raise UnboundLocalError."""
        self.mod.OPENCODE_LANES = False
        unit, tid, err = self.mod.start_task(
            _card(lane="free_lane",
                  model="litellm/gemini-3.5-flash-lite"), "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(unit, "devin-task-fake-tid-123")
        self.assertEqual(tid, "fake-tid-123")

    def test_explicit_lane_routes_to_opencode_when_enabled(self):
        """Explicit model lane + OPENCODE_LANES=1 -> OpenCode executor."""
        self.mod.OPENCODE_LANES = True
        seen = []
        self.mod.start_opencode_lane = lambda card, lane, unit: (
            seen.append(lane) or ("devin-task-x", "x", ""))
        unit, tid, err = self.mod.start_task(
            _card(lane="free_lane"), "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(seen, ["free_lane"])
        self.assertEqual(unit, "devin-task-x")

    def test_unset_lane_classifies_and_persists(self):
        """Unset lane -> classify_lane result persisted on the action."""
        self.mod.OPENCODE_LANES = False
        self.mod.classify_lane = lambda card: "paid_frontier"
        card = _card()
        unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(card["action"]["lane"], "paid_frontier")
        self.assertEqual(card["action"]["model"],
                         "litellm/or-claude-fable-5.1")

    def test_unset_lane_classified_free_lane_uses_opencode(self):
        self.mod.OPENCODE_LANES = True
        self.mod.classify_lane = lambda card: "free_lane"
        seen = []
        self.mod.start_opencode_lane = lambda card, lane, unit: (
            seen.append(lane) or ("devin-task-y", "y", ""))
        card = _card()
        unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(seen, ["free_lane"])

    def test_classified_manual_is_refused_not_dispatched(self):
        """manual lane = Tony's hands — fail loudly, never burn tokens."""
        self.mod.classify_lane = lambda card: "manual"
        card = _card()
        unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(unit, "")
        self.assertIn("manual", err)
        self.assertFalse(self.calls)  # no devin-dispatch spawn
        self.assertNotIn("lane", card["action"])  # manual never persisted


if __name__ == "__main__":
    unittest.main()
