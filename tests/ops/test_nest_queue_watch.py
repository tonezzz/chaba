"""Regression tests for current and legacy Ada Nest queue log monitoring."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ops/nest-queue-watch.py"

spec = importlib.util.spec_from_file_location("nest_queue_watch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["nest_queue_watch"] = mod
spec.loader.exec_module(mod)


class LogDiscovery(unittest.TestCase):
    def test_new_format_wins_over_legacy_log(self):
        listing = "\n".join([
            "run-20261023-1028.out.log",
            "log-20261023-1233.txt",
            "log-20261023-1215.txt",
            "heartbeat",
        ])
        self.assertEqual(mod.newest_log(listing), "log-20261023-1233.txt")

    def test_legacy_format_remains_supported(self):
        self.assertEqual(
            mod.newest_log("run-20261023-1028.out.log\nheartbeat\n"),
            "run-20261023-1028.out.log")

    def test_prep_event_is_understood(self):
        match = mod.EVENT.match("11:38:05 == doc-embeds-ss1: prep (foreground)")
        self.assertIsNotNone(match)
        self.assertEqual(mod.fmt_event(match), "doc-embeds-ss1 — preparing")


class WatchTick(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state, self.old_off = mod.STATE, mod.OFF_FILE
        mod.STATE = Path(self.tmp.name) / "state.json"
        mod.OFF_FILE = Path(self.tmp.name) / "disabled"
        self.log_name = "log-20261023-2010.txt"
        self.log_text = "\n".join([
            "11:00:00 lease acquired: colab-worker epoch 4",
            "11:00:01 == doc-embeds-ss1: prep (foreground)",
            "11:00:02 == doc-embeds-ss1: run (gpu 0 %, 0 MiB)",
            "11:00:03 == doc-embeds-ss1: DONE 10s",
        ])

    def tearDown(self):
        mod.STATE, mod.OFF_FILE = self.old_state, self.old_off
        self.tmp.cleanup()

    def remote(self, *args):
        if args[0] == "cat" and args[1].endswith("/heartbeat"):
            return f"{int(time.time())} doc-embeds-ss1 run"
        if args[0] == "lsf":
            self.assertIn("run-*.out.log", args)
            self.assertIn("log-*.txt", args)
            return "run-20261023-1028.out.log\n" + self.log_name + "\n"
        if args[0] == "cat" and args[1].endswith("/" + self.log_name):
            return self.log_text
        self.fail(f"unexpected remote call: {args}")

    def test_notifies_events_from_current_runner_log(self):
        with patch.object(mod, "remote", side_effect=self.remote), \
                patch.object(mod.board_notify, "send", return_value=True) \
                as send:
            self.assertEqual(mod.main(), 0)
        messages = [call.args[0] for call in send.call_args_list]
        self.assertEqual(len(messages), 4)
        self.assertIn("doc-embeds-ss1 — started", messages[2])
        self.assertIn("doc-embeds-ss1 — done", messages[3])
        self.assertEqual(mod.load_state()["log"], self.log_name)

    def test_failed_delivery_does_not_advance_cursor(self):
        with patch.object(mod, "remote", side_effect=self.remote), \
                patch.object(mod.board_notify, "send", return_value=False):
            self.assertEqual(mod.main(), 0)
        self.assertFalse(mod.STATE.exists())


if __name__ == "__main__":
    unittest.main()
