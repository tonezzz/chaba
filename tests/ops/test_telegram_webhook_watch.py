"""Tests for Telegram webhook drift monitoring; no live Bot API calls."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ops/telegram-webhook-watch.py"
spec = importlib.util.spec_from_file_location("telegram_webhook_watch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["telegram_webhook_watch"] = mod
spec.loader.exec_module(mod)


class FetchStatus(unittest.TestCase):
    def test_registered_webhook_is_healthy(self):
        payload = {"ok": True, "result": {
            "url": mod.EXPECTED_URL, "pending_update_count": 0}}
        with patch.object(mod.urllib.request, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = (
                json.dumps(payload).encode())
            issue, _ = mod.fetch_status("dummy")
        self.assertEqual(issue, "")

    def test_missing_url_and_pending_updates_are_reported(self):
        payload = {"ok": True, "result": {
            "url": "", "pending_update_count": 3}}
        with patch.object(mod.urllib.request, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = (
                json.dumps(payload).encode())
            issue, result = mod.fetch_status("dummy")
        self.assertEqual(issue, "url-mismatch,pending-3")
        self.assertIn("unset", mod.issue_message(issue, result))
        self.assertIn("3 updates", mod.issue_message(issue, result))

    def test_http_error_does_not_include_token_in_issue(self):
        error = mod.urllib.error.HTTPError(
            "https://api.telegram.org/botsecret/getWebhookInfo",
            401, "unauthorized", {}, None)
        with patch.object(mod.urllib.request, "urlopen", side_effect=error):
            issue, result = mod.fetch_status("secret")
        self.assertEqual(issue, "telegram-http-401")
        self.assertIsNone(result)
        self.assertNotIn("secret", issue)


class AlertState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state = mod.STATE_FILE
        mod.STATE_FILE = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        mod.STATE_FILE = self.old_state
        self.tmp.cleanup()

    def test_notifies_only_on_change_and_on_recovery(self):
        with patch.object(mod, "fetch_status",
                          return_value=("url-mismatch", {
                              "url": "", "pending_update_count": 0})), \
                patch.object(mod.board_notify, "send",
                             return_value=True) as send:
            self.assertEqual(mod.run(), 1)
            self.assertEqual(mod.run(), 1)
            self.assertEqual(send.call_count, 1)

            with patch.object(mod, "fetch_status",
                              return_value=("", {
                                  "url": mod.EXPECTED_URL,
                                  "pending_update_count": 0})):
                self.assertEqual(mod.run(), 0)
            self.assertEqual(send.call_count, 2)
            self.assertIn("recovered", send.call_args.args[0])

    def test_failed_alert_is_retried(self):
        with patch.object(mod, "fetch_status",
                          return_value=("url-mismatch", {"url": ""})), \
                patch.object(mod.board_notify, "send",
                             return_value=False) as send:
            self.assertEqual(mod.run(), 1)
            self.assertFalse(mod.STATE_FILE.exists())
            self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
