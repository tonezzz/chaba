"""Exit-status contract for retry-storm-watch.

A finding that was filed (or dedup-muted) into the board inbox is a
completed activation: rc=0. Nonzero is reserved for a failed inbox write
or a --no_alert dry run, so timer-sentinel does not file false timer
failure cards for every real alert (timer-alert-idc02-retry-storm-watch).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ops" / "retry-storm-watch.py"

spec = importlib.util.spec_from_file_location("retry_storm_watch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["retry_storm_watch"] = mod
spec.loader.exec_module(mod)


def run_main(argv, *, problems=None, filed=True, muted=False):
    state = {"alerts": {}}
    problems = [("cpu:test-container", "hot for 30min")] \
        if problems is None else problems
    with patch.object(sys, "argv", ["retry-storm-watch.py", *argv]), \
            patch.object(mod, "load_state", lambda: state), \
            patch.object(mod, "podman_names", lambda: []), \
            patch.object(mod, "check_cpu", lambda st, args: problems), \
            patch.object(mod, "check_logs", lambda st, args, names: []), \
            patch.object(mod, "check_mddb", lambda st, args: []), \
            patch.object(mod, "recently_alerted", lambda st, c, h: muted), \
            patch.object(mod, "file_inbox",
                         side_effect=lambda text: filed) as file_inbox, \
            patch.object(mod, "save_state", lambda st: None):
        rc = mod.main()
    return rc, file_inbox.call_count, state


class ExitContract(unittest.TestCase):
    def test_filed_alert_is_successful_activation(self):
        rc, filed, state = run_main(["--checks", "cpu"])
        self.assertEqual(rc, 0)
        self.assertEqual(filed, 1)
        self.assertIn("cpu:test-container", state["alerts"])

    def test_dedup_muted_alert_is_successful_activation(self):
        rc, filed, state = run_main(["--checks", "cpu"], muted=True)
        self.assertEqual(rc, 0)
        self.assertEqual(filed, 0)
        self.assertNotIn("cpu:test-container", state["alerts"])

    def test_inbox_delivery_failure_still_fails(self):
        rc, filed, state = run_main(["--checks", "cpu"], filed=False)
        self.assertEqual(rc, 1)
        self.assertEqual(filed, 1)
        self.assertNotIn("cpu:test-container", state["alerts"])

    def test_no_alert_dry_run_reports_findings_via_rc(self):
        rc, filed, state = run_main(["--checks", "cpu", "--no-alert"])
        self.assertEqual(rc, 1)
        self.assertEqual(filed, 0)
        self.assertNotIn("cpu:test-container", state["alerts"])

    def test_clean_run_exits_zero(self):
        rc, filed, state = run_main(["--checks", "cpu"], problems=[])
        self.assertEqual(rc, 0)
        self.assertEqual(filed, 0)


if __name__ == "__main__":
    unittest.main()
