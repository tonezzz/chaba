import json
import time
import unittest
from unittest.mock import patch

from scripts.devnest.kk_mac_admission import snapshot


def doc(body):
    return {"contentMd": json.dumps(body)}


class KkMacAdmissionTests(unittest.TestCase):
    def test_fresh_healthy_heartbeat_is_eligible(self):
        now = time.time()
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "KKs-Mac-Studio",
                "ts": now - 30,
                "ollama_ok": True,
                "disk_free_gb": 78,
            })],
        ):
            result = snapshot(now=now)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["reasons"], [])

    def test_stale_heartbeat_fails_closed(self):
        now = time.time()
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "KKs-Mac-Studio",
                "ts": now - 901,
                "ollama_ok": True,
                "disk_free_gb": 78,
            })],
        ):
            result = snapshot(now=now)
        self.assertFalse(result["eligible"])
        self.assertIn("heartbeat_stale", result["reasons"])

    def test_unhealthy_or_low_disk_fails_closed(self):
        now = time.time()
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "KKs-Mac-Studio",
                "ts": now - 30,
                "ollama_ok": False,
                "disk_free_gb": 19,
            })],
        ):
            result = snapshot(now=now)
        self.assertFalse(result["eligible"])
        self.assertEqual(
            result["reasons"], ["ollama_unhealthy", "disk_low"]
        )

    def test_missing_heartbeat_fails_closed(self):
        with patch("scripts.devnest.kk_mac_admission._search", return_value=[]):
            result = snapshot()
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reasons"], ["heartbeat_missing"])
