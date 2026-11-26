"""Tests for scripts/devnest/opencode_stream_guard.py — the
denial-streak circuit breaker for headless opencode dispatch units
(card runner-dispatch-no-timeout)."""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/devnest/opencode_stream_guard.py"

spec = importlib.util.spec_from_file_location(
    "opencode_stream_guard", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["opencode_stream_guard"] = mod
spec.loader.exec_module(mod)


def _denial(i=0):
    return json.dumps({"part": {"tool": "bash", "state": {
        "status": "error",
        "error": f"Permission denied by rule #{i}"}}}) + "\n"


def _done(i=0):
    return json.dumps({"part": {"tool": "bash", "state": {
        "status": "completed", "output": f"ok {i}"}}}) + "\n"


def _text(t="thinking"):
    return json.dumps({"part": {"type": "text", "text": t}}) + "\n"


class GuardStreamTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.events = Path(self.td.name) / "events.jsonl"
        self.marker = Path(self.td.name) / "denial-breaker.json"
        self.out = io.StringIO()
        self.deny_re = mod._deny_re()

    def _run(self, lines, max_streak=3):
        return mod.guard_stream(iter(lines), self.events, max_streak,
                                self.marker, self.deny_re, out=self.out)

    def test_clean_stream_passes_through(self):
        lines = [_text(), _done(1), _done(2), _text("bye")]
        n, breaker = self._run(lines)
        self.assertEqual(n, 4)
        self.assertIsNone(breaker)
        self.assertEqual(self.events.read_text(), "".join(lines))
        self.assertEqual(self.out.getvalue(), "".join(lines))

    def test_denial_streak_trips_breaker(self):
        lines = [_done(1), _denial(1), _denial(2), _denial(3),
                 _denial(4)]
        n, breaker = self._run(lines, max_streak=3)
        self.assertIsNotNone(breaker)
        self.assertTrue(breaker["tripped"])
        self.assertEqual(breaker["streak"], 3)
        self.assertEqual(breaker["max_streak"], 3)
        # stream stops at the tripping line — the tail is not consumed
        self.assertEqual(n, 4)

    def test_completed_tool_call_resets_streak(self):
        lines = [_denial(1), _denial(2), _done(1),
                 _denial(3), _denial(4)]
        n, breaker = self._run(lines, max_streak=3)
        self.assertIsNone(breaker)
        self.assertEqual(n, 5)

    def test_text_between_denials_does_not_reset(self):
        # the doom-loop shape: denial -> think -> denial -> think ...
        lines = []
        for i in range(4):
            lines += [_denial(i), _text(f"retry {i}")]
        n, breaker = self._run(lines, max_streak=4)
        self.assertIsNotNone(breaker)
        self.assertEqual(breaker["streak"], 4)

    def test_non_error_tool_events_ignored(self):
        lines = [_denial(1), _denial(2),
                 json.dumps({"part": {"tool": "bash", "state": {
                     "status": "running"}}}) + "\n",
                 _denial(3)]
        n, breaker = self._run(lines, max_streak=3)
        self.assertIsNotNone(breaker)
        self.assertEqual(breaker["streak"], 3)


class GuardCliTest(unittest.TestCase):
    """End-to-end: guard wraps a child, kills it on the streak, writes
    the marker, exits 3."""

    def test_cli_kills_child_and_marks(self):
        with tempfile.TemporaryDirectory() as td:
            events = Path(td) / "events.jsonl"
            marker = Path(td) / "denial-breaker.json"
            child = (
                "import sys,time,json;"
                "line=json.dumps({'part':{'tool':'bash','state':{"
                "'status':'error','error':'denied by rule'}}})+'\\n';"
                "[print(line,end='',flush=True) or time.sleep(0.05) "
                "for _ in range(200)];"
                "time.sleep(60)")
            r = subprocess.run(
                [sys.executable, "-u", str(SCRIPT),
                 "--events", str(events), "--max-streak", "5",
                 "--marker", str(marker), "--kill-grace", "1",
                 "--", sys.executable, "-u", "-c", child],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 3, r.stderr[-500:])
            self.assertTrue(marker.is_file())
            rec = json.loads(marker.read_text())
            self.assertTrue(rec["tripped"])
            self.assertGreaterEqual(rec["streak"], 5)
            self.assertTrue(events.is_file())
            self.assertIn("denial streak", r.stderr)

    def test_cli_passthrough_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            events = Path(td) / "events.jsonl"
            r = subprocess.run(
                [sys.executable, "-u", str(SCRIPT),
                 "--events", str(events), "--max-streak", "5",
                 "--", sys.executable, "-c",
                 "print('hello')"],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0)
            self.assertIn("hello", r.stdout)
            self.assertEqual(events.read_text().strip(), "hello")


if __name__ == "__main__":
    unittest.main()
