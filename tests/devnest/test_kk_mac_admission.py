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

    def test_old_heartbeat_uses_read_only_ssh_load_fallback(self):
        now = time.time()
        with patch(
            "scripts.devnest.kk_mac_admission._search",
            return_value=[doc({
                "host": "KKs-Mac-Studio",
                "ts": now - 30,
                "ollama_ok": True,
                "disk_free_gb": 78,
            })],
        ), patch(
            "scripts.devnest.kk_mac_admission._ssh_load",
            return_value=1.5,
        ):
            result = snapshot(now=now)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["load_source"], "ssh_read_only_fallback")

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

    def test_alias_prefers_freshest_shadow_doc(self):
        # renamed host keys accumulate alias docs under one tailnet_ip —
        # a stale shadow must not deny the fresh canonical heartbeat
        now = time.time()
        docs = [
            doc({"host": "192", "tailnet_ip": "100.108.217.17",
                 "ts": now - 30000, "ollama_ok": True,
                 "disk_free_gb": 55}),  # stale alias, listed first
            doc({"host": "New-Name", "tailnet_ip": "100.108.217.17",
                 "ts": now - 60, "ollama_ok": True,
                 "disk_free_gb": 79, "load_1m": 1.5}),
        ]
        with patch("scripts.devnest.kk_mac_admission._search",
                   return_value=docs):
            result = snapshot(host="kk-mac", now=now)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["disk_free_gb"], 79)

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


class QuietHoursTests(unittest.TestCase):
    """quiet_hours_active: do-not-run window in kk-mac local time (ICT
    +7), wraps midnight; malformed windows return None so callers can
    fail closed."""

    def _ts(self, hm):
        # anchor an ICT wall-clock time: 2026-11-20 is a Friday; the
        # helper only reads hour/minute in the +7 zone.
        from datetime import datetime, timedelta, timezone
        h, m = (int(x) for x in hm.split(":"))
        dt = datetime(2026, 11, 20, h, m,
                      tzinfo=timezone(timedelta(hours=7)))
        return dt.timestamp()

    def test_inside_simple_window(self):
        from scripts.devnest.kk_mac_admission import quiet_hours_active
        self.assertIs(quiet_hours_active("23:00-07:00",
                                         now=self._ts("23:30")), True)
        self.assertIs(quiet_hours_active("23:00-07:00",
                                         now=self._ts("02:15")), True)

    def test_outside_window(self):
        from scripts.devnest.kk_mac_admission import quiet_hours_active
        self.assertIs(quiet_hours_active("23:00-07:00",
                                         now=self._ts("12:00")), False)
        self.assertIs(quiet_hours_active("23:00-07:00",
                                         now=self._ts("07:00")), False)
        self.assertIs(quiet_hours_active("08:00-18:00",
                                         now=self._ts("09:00")), True)

    def test_malformed_windows(self):
        from scripts.devnest.kk_mac_admission import quiet_hours_active
        for bad in ("", "overnight", "23-07", "25:00-07:00",
                    "23:60-07:00", "07:00-07:00"):
            self.assertIsNone(quiet_hours_active(bad,
                                                 now=self._ts("12:00")),
                              msg=bad)
