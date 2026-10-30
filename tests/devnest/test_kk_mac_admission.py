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
                "load_1m": 1.2,
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
                "load_1m": 1.2,
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
                "load_1m": 1.2,
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

    def test_high_load_fails_closed(self):
        now = time.time()
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "KKs-Mac-Studio",
                "ts": now - 30,
                "ollama_ok": True,
                "disk_free_gb": 78,
                "load_1m": 4.1,
            })],
        ):
            result = snapshot(now=now)
        self.assertFalse(result["eligible"])
        self.assertIn("load_high", result["reasons"])

    def test_old_ip_key_can_match_by_tailnet_identity(self):
        now = time.time()
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "192",
                "tailnet_ip": "100.108.217.17",
                "ts": now - 30,
                "ollama_ok": True,
                "disk_free_gb": 78,
                "load_1m": 1.2,
            })],
        ):
            result = snapshot(now=now)
        self.assertTrue(result["eligible"])
        self.assertTrue(result["identity_alias"])

    def test_busy_node_defers_lane(self):
        now = time.time()
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "KKs-Mac-Studio",
                "ts": now - 30,
                "ollama_ok": True,
                "disk_free_gb": 78,
                "load_1m": 1.2,
                "tmux_jobs": "vimax-render",
            })],
        ):
            result = snapshot(now=now)
        self.assertFalse(result["eligible"])
        self.assertTrue(result["node_busy"])
        self.assertIn("node_busy:tmux_jobs", result["reasons"])
        # an idle tmux_jobs field does not block
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "KKs-Mac-Studio",
                "ts": now - 30,
                "ollama_ok": True,
                "disk_free_gb": 78,
                "load_1m": 1.2,
                "tmux_jobs": "",
            })],
        ):
            result = snapshot(now=now)
        self.assertTrue(result["eligible"])

    def test_load_signals_gate_overload(self):
        now = time.time()
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "KKs-Mac-Studio",
                "ts": now - 30,
                "ollama_ok": True,
                "disk_free_gb": 78,
                "load_ok": False,
                "load_1m": 1.2,
            })],
        ):
            result = snapshot(now=now)
        self.assertFalse(result["eligible"])
        self.assertIn("node_busy:load_ok", result["reasons"])
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "KKs-Mac-Studio",
                "ts": now - 30,
                "ollama_ok": True,
                "disk_free_gb": 78,
                "load1": 30.0,
                "cpu_cores": 14,
            })],
        ):
            result = snapshot(now=now)
        self.assertFalse(result["eligible"])
        self.assertIn("node_busy:load1", result["reasons"])
