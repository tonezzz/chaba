"""Unit test for kanban-dispatch.py build_task — REPORT_RAILS is appended
iff the card carries `report: <slug>` (report-session-loop design §2b).

Imports the dash-named module via importlib; no dispatch, no git.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/kanban-dispatch.py"
sys.path.insert(0, str(REPO / "scripts" / "board"))  # dispatch_repos import


def _load():
    spec = importlib.util.spec_from_file_location("kanban_dispatch", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BuildTaskRailsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()
        # build_task() runs the lesson primer — a full docs/ssot rescan +
        # MDDB fetch per call (~100s). These tests assert rails text only;
        # primer integration is covered by test_build_task_regressions.
        cls._primer_off = mock.patch.dict(
            os.environ, {"KANBAN_PRIMER": "0", "KANBAN_PRIMER_GOOD": "0"})
        cls._primer_off.start()

    @classmethod
    def tearDownClass(cls):
        cls._primer_off.stop()

    def test_report_rails_appended_when_report_set(self):
        card = {"id": "c1", "title": "t", "report": "dev-kanban",
                "action": {"type": "dispatch"}}
        task = self.mod.build_task(card)
        self.assertIn("This card is report-linked: ada-cms-pages/dev-kanban",
                      task)
        self.assertIn("cms-report-note.py dev-kanban --read", task)
        self.assertIn("cms-report-note.py dev-kanban --note", task)
        # rails order: REPORT_RAILS comes after TASK_RAILS
        self.assertLess(task.index("Rails: you are processing kanban card"),
                        task.index("This card is report-linked"))

    def test_no_report_rails_without_report(self):
        card = {"id": "c2", "title": "t",
                "action": {"type": "dispatch"}}
        task = self.mod.build_task(card)
        self.assertIn("Rails: you are processing kanban card 'c2'", task)
        self.assertNotIn("report-linked", task)
        self.assertNotIn("cms-report-note", task)

    def test_blank_report_is_ignored(self):
        card = {"id": "c3", "title": "t", "report": "  ",
                "action": {"type": "dispatch"}}
        self.assertNotIn("report-linked", self.mod.build_task(card))


if __name__ == "__main__":
    unittest.main()
