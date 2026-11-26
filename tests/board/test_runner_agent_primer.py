"""Regression tests for the runner-agent devin-path primer
(runner-agent-primer-coverage).

pre-fix, runner-agent.start_task built the dispatch prompt as plain
spec + RAILS — no lp.build, no KNOWN_PITFALLS, no RETRY_RAILS — so the
~96% of dispatches it carries ran unprimed. The devin path now shares
dispatch_task.build_task_text with kanban-dispatch.build_task:

- KNOWN_PITFALLS / KNOWN_GOOD render when the primer has lines
- KANBAN_PRIMER=0 / KANBAN_PRIMER_GOOD=0 stay honored (warn-only,
  never consulted)
- a retry card gets RETRY_RAILS (attempt N + prior failure)
- dt_module() resolving to None falls back to spec + RAILS, warn-only
- claim_pass posts the 'primer injected N lesson(s)' comms note, same
  shape as kanban-dispatch start_pending

lesson_primer.build / build_good are monkeypatched so the primer path
is deterministic — no repo walk, no MDDB fetch, no dispatch spawn.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ["BOARD_API_COMMIT"] = "0"

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
SCRIPT = REPO / "scripts" / "board" / "runner-agent.py"

import lesson_primer  # noqa: E402 — patched below

PRIMER_MARK = "KNOWN_PITFALLS — lessons harvested"
GOOD_MARK = "KNOWN_GOOD"


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
    return {"id": "primer-card", "title": "primer test",
            "spec": "do a thing", "column": "backlog", "action": a}


class DevinPathPrimerTest(unittest.TestCase):
    """start_task's devin path composes through dispatch_task."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in
                       ("OPENCODE_LANES", "DISPATCH", "HOST")}
        self._saved_fn = {k: getattr(m, k) for k in
                          ("sh", "classify_lane", "dr_module",
                           "enforce_task_limits", "task_runtime")}
        m.DISPATCH = str(SCRIPT)      # exists -> dispatch executor present
        m.dr_module = lambda: None
        m.enforce_task_limits = lambda *a, **k: None
        m.task_runtime = lambda: "systemd"
        self.calls = []
        m.sh = lambda argv, **kw: self.calls.append(argv) or _proc(
            0, "fake-tid-123\n")

    def tearDown(self):
        m = self.mod
        for k, v in {**self._saved, **self._saved_fn}.items():
            setattr(m, k, v)

    def _task_arg(self):
        """The composed prompt is argv[3] of `<dispatch> start <repo>
        <task>` — the only spawn these tests allow."""
        self.assertEqual(len(self.calls), 1)
        argv = self.calls[0]
        self.assertEqual(argv[0], str(SCRIPT))
        self.assertEqual(argv[1], "start")
        return argv[3]

    def test_known_pitfalls_renders_on_devin_path(self):
        with mock.patch.object(lesson_primer, "build",
                               return_value=["never do the thing"]) as b, \
             mock.patch.object(lesson_primer, "build_good",
                               return_value=[]):
            unit, tid, err = self.mod.start_task(
                _card(executor="devin"), "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(unit, "devin-task-fake-tid-123")
        b.assert_called_once()
        task = self._task_arg()
        self.assertIn(PRIMER_MARK, task)
        self.assertIn("- never do the thing", task)

    def test_known_good_renders(self):
        with mock.patch.object(lesson_primer, "build", return_value=[]), \
             mock.patch.object(lesson_primer, "build_good",
                               return_value=["the thing worked"]):
            unit, tid, err = self.mod.start_task(
                _card(executor="devin"), "dispatch")
        self.assertEqual(err, "")
        task = self._task_arg()
        self.assertIn(GOOD_MARK, task)
        self.assertIn("the thing worked", task)

    def test_primer_env_off_suppresses_block(self):
        with mock.patch.dict(os.environ,
                             {"KANBAN_PRIMER": "0",
                              "KANBAN_PRIMER_GOOD": "0"}), \
             mock.patch.object(lesson_primer, "build",
                               return_value=["a lesson"]) as b, \
             mock.patch.object(lesson_primer, "build_good",
                               return_value=["a good"]) as g:
            unit, tid, err = self.mod.start_task(
                _card(executor="devin"), "dispatch")
        self.assertEqual(err, "")
        b.assert_not_called()
        g.assert_not_called()
        task = self._task_arg()
        self.assertNotIn(PRIMER_MARK, task)
        self.assertNotIn(GOOD_MARK, task)

    def test_retry_rails_on_requeue(self):
        with mock.patch.object(lesson_primer, "build", return_value=[]), \
             mock.patch.object(lesson_primer, "build_good",
                               return_value=[]):
            unit, tid, err = self.mod.start_task(
                _card(executor="devin", attempts=1,
                      last_failure="boom"), "dispatch")
        self.assertEqual(err, "")
        task = self._task_arg()
        self.assertIn("This is attempt 2", task)
        self.assertIn("boom", task)

    def test_report_rails_on_report_linked(self):
        with mock.patch.object(lesson_primer, "build", return_value=[]), \
             mock.patch.object(lesson_primer, "build_good",
                               return_value=[]):
            card = _card(executor="devin")
            card["report"] = "some-report"
            unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(err, "")
        task = self._task_arg()
        self.assertIn("report-linked: ada-cms-pages/some-report", task)

    def test_module_unresolved_falls_back_warn_only(self):
        """No importable dispatch_task -> plain spec + RAILS, still
        launches — the primer is advisory, never a claim blocker."""
        m = self.mod
        saved = m.dt_module
        m.dt_module = lambda: None
        try:
            with mock.patch.object(lesson_primer, "build") as b:
                unit, tid, err = m.start_task(
                    _card(executor="devin"), "dispatch")
        finally:
            m.dt_module = saved
        self.assertEqual(err, "")
        self.assertEqual(unit, "devin-task-fake-tid-123")
        b.assert_not_called()
        task = self._task_arg()
        self.assertIn("on runner", task)          # legacy RAILS shape
        self.assertNotIn(PRIMER_MARK, task)

    def test_module_build_exception_falls_back(self):
        """A dispatch_task import that raises inside build_task_text
        still falls back to spec + RAILS — warn-only."""
        m = self.mod
        saved = m.dt_module

        class _Boom:
            @staticmethod
            def build_task_text(card, host, api):
                raise RuntimeError("corrupt checkout")

        m.dt_module = lambda: _Boom
        try:
            unit, tid, err = m.start_task(
                _card(executor="devin"), "dispatch")
        finally:
            m.dt_module = saved
        self.assertEqual(err, "")
        task = self._task_arg()
        self.assertIn("on runner", task)
        self.assertNotIn(PRIMER_MARK, task)


class PrimerCommsTest(unittest.TestCase):
    """claim_pass logs injected lines after 'started' — same message
    shape as kanban-dispatch start_pending."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved_env = os.environ.get("JEV_LANE")
        os.environ["JEV_LANE"] = "0"
        self._saved = {k: getattr(m, k) for k in ("DISPATCH",)}
        self._saved_fn = {k: getattr(m, k) for k in
                          ("api", "start_task", "push_capable",
                           "gpu_preflight", "classify_lane", "dr_module",
                           "overloaded", "note_defer", "task_runtime",
                           "RETRY_FILE")}
        m.DISPATCH = str(SCRIPT)
        m.task_runtime = lambda: "systemd"
        self._tmpdir = tempfile.TemporaryDirectory()
        m.RETRY_FILE = Path(self._tmpdir.name) / "retry-ledger.json"
        m.dr_module = lambda: None
        m.push_capable = lambda repo: True
        m.gpu_preflight = lambda card: ""
        m.overloaded = lambda: False
        m.note_defer = lambda *a, **k: None
        m.classify_lane = lambda card: "devin"
        self.posts = []

        def fake_api(path, body=None):
            if path == "/cards":
                return {"cards": self.cards}
            self.posts.append((path, dict(body or {})))
            return {}
        m.api = fake_api
        self.cards = []

    def tearDown(self):
        m = self.mod
        if self._saved_env is None:
            os.environ.pop("JEV_LANE", None)
        else:
            os.environ["JEV_LANE"] = self._saved_env
        for k, v in {**self._saved, **self._saved_fn}.items():
            setattr(m, k, v)
        self._tmpdir.cleanup()

    def test_primer_lines_logged_to_comms(self):
        m = self.mod
        m.start_task = lambda card, typ: (
            m.LAST_PRIMER_LINES.extend(["never do the thing",
                                        "or the other thing"]),
            m.LAST_GOOD_LINES.extend(["the thing worked"]),
            ("devin-task-t", "t", ""))[2]
        self.cards = [_card(executor="devin")]
        self.assertTrue(m.claim_pass({}))
        texts = [b["text"] for p, b in self.posts if p == "/comment"]
        note = next((t for t in texts if t.startswith("primer injected")),
                    "")
        self.assertEqual(
            note, "primer injected 2 lesson(s): never do the thing; "
                  "or the other thing | good: the thing worked")
        self.assertFalse(m.LAST_PRIMER_LINES)   # consumed, not re-posted
        self.assertFalse(m.LAST_GOOD_LINES)

    def test_no_primer_no_note(self):
        m = self.mod
        m.start_task = lambda card, typ: ("devin-task-t", "t", "")
        self.cards = [_card(executor="devin")]
        self.assertTrue(m.claim_pass({}))
        texts = [b["text"] for p, b in self.posts if p == "/comment"]
        self.assertFalse(
            any(t.startswith("primer injected") for t in texts))


if __name__ == "__main__":
    unittest.main()
