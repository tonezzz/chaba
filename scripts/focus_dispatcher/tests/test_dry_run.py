"""Dry-run tests for focus_dispatcher public API.

These tests make sure activate_inbox, next_focus, and safe_to_dispatch can be
run with dry_run=True without writing to the canonical SSOT files.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from focus_dispatcher.actions import activate_inbox, next_focus
from focus_dispatcher.triage import safe_to_dispatch


class TestDryRun(unittest.TestCase):
    @staticmethod
    def _current_doc():
        return {
            "validation": {"max_active_shared_focus": 1, "max_active_branch_focus": 1},
            "sections": [
                {"title": "Active Shared Focus", "items": []},
                {"title": "Active Branch Focus", "items": []},
                {"title": "Ready (Safe)", "items": []},
                {"title": "Hand-off Queue", "items": []},
            ],
        }

    @staticmethod
    def _focus_doc():
        return {
            "sections": [
                {
                    "title": "Backlog - Triage Queue",
                    "items": [
                        {
                            "label": "Parked backlog focus",
                            "text": "A parked focus for testing.",
                            "status": "parked",
                            "priority": "medium",
                            "source": "/path/to/ssot.focus.yml",
                        }
                    ],
                }
            ]
        }

    def test_activate_inbox_dry_run_does_not_save(self):
        inbox = {
            "label": "Test inbox focus",
            "text": "A test focus.",
            "priority": "medium",
            "__file": Path("/tmp/test-inbox.yml"),
        }

        with patch("focus_dispatcher.actions.load_current", return_value=self._current_doc()), \
             patch("focus_dispatcher.actions.save_current") as mock_save, \
             patch("focus_dispatcher.actions.git_mv_inbox") as mock_mv:
            section, item, target = activate_inbox(inbox, dry_run=True)

        self.assertEqual(section, "Active Shared Focus")
        self.assertEqual(item["label"], "Test inbox focus")
        self.assertEqual(item["status"], "active")
        self.assertIn("test-inbox", str(target))
        mock_save.assert_not_called()
        mock_mv.assert_not_called()

    def test_next_focus_dry_run_does_not_save(self):
        current = self._current_doc()
        current["sections"][1]["items"].append({
            "label": "Completed branch focus",
            "status": "completed",
            "priority": "medium",
            "subtasks": [],
        })

        with patch("focus_dispatcher.actions.load_current", return_value=current), \
             patch("focus_dispatcher.actions.load_focus", return_value=self._focus_doc()), \
             patch("focus_dispatcher.actions._inbox_items", return_value=[]), \
             patch("focus_dispatcher.actions.save_current") as mock_save_current, \
             patch("focus_dispatcher.actions.save_focus") as mock_save_focus:
            result = next_focus(dry_run=True)

        self.assertTrue(result.get("ok"), result.get("error"))
        self.assertTrue(result.get("activated"))
        self.assertEqual(result["next"]["label"], "Parked backlog focus")
        mock_save_current.assert_not_called()
        mock_save_focus.assert_not_called()

    def test_safe_to_dispatch_does_not_write(self):
        current = self._current_doc()
        current["sections"][1]["items"].append({
            "label": "Active branch focus",
            "status": "active",
            "priority": "medium",
        })
        focus = self._focus_doc()
        focus["sections"][0]["items"][0]["status"] = "active"
        focus["sections"][0]["items"][0]["safe_to_parallel"] = True

        with patch("focus_dispatcher.triage.load_current", return_value=current), \
             patch("focus_dispatcher.triage.load_focus", return_value=focus), \
             patch("focus_dispatcher.triage.inbox_items", return_value=[]), \
             patch("focus_dispatcher.state.save_current") as mock_save:
            item = safe_to_dispatch()

        self.assertIsNotNone(item)
        self.assertEqual(item["label"], "Parked backlog focus")
        mock_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
