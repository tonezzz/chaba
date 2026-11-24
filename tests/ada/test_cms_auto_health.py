"""Unit tests for scripts/ada/cms-auto-health.py — the generator-host
reachability gate (card cms-auto-health-stop-carding-powered-off).

Covers: `tailscale status --json` parsing into a label->online map
(HostName, DNSName first label, TailscaleIPs, self), fail-open on
tailscale outage / unknown peer, and host_gate demoting
stale/error/dead verdicts to host-down only when the generator host is
confirmed tailnet-offline.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ada" / "cms-auto-health.py"

spec = importlib.util.spec_from_file_location("cms_auto_health", SCRIPT)
cah = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cah)

NOW = time.time()
OLD_ISO = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()


def ts_status_doc():
    return {
        "Self": {"HostName": "tony-dell",
                 "DNSName": "tony-dell.taila0626a.ts.net.",
                 "TailscaleIPs": ["100.68.142.13"]},
        "Peer": {
            "nodekey:a": {"HostName": "tony-macbook",
                          "DNSName": "tony-macbook.taila0626a.ts.net.",
                          "Online": False,
                          "TailscaleIPs": ["100.77.76.112"]},
            "nodekey:b": {"HostName": "tony-omen",
                          "DNSName": "tony-omen.taila0626a.ts.net.",
                          "Online": True,
                          "TailscaleIPs": ["100.75.102.88"]},
            # hostname != tailnet name (mn01's HostName is tony-mn)
            "nodekey:c": {"HostName": "tony-mn",
                          "DNSName": "mn01.taila0626a.ts.net.",
                          "Online": True,
                          "TailscaleIPs": ["100.106.196.22"]},
        },
    }


def proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class HostOnlineTest(unittest.TestCase):
    def setUp(self):
        cah._TS_PROBED = False
        cah._TS_PEERS = None

    def tearDown(self):
        cah._TS_PROBED = False
        cah._TS_PEERS = None

    def test_peer_online_offline_self_ip_and_aliases(self):
        with patch.object(cah.subprocess, "run",
                          return_value=proc(0, json.dumps(ts_status_doc()))):
            self.assertIs(cah.host_online("tony-macbook"), False)
            self.assertIs(cah.host_online("tony-omen"), True)
            self.assertIs(cah.host_online("mn01"), True)       # DNSName label
            self.assertIs(cah.host_online("tony-mn"), True)    # HostName label
            self.assertIs(cah.host_online("tony-dell"), True)  # self
            self.assertIs(cah.host_online("100.77.76.112"), False)  # tailnet IP
            self.assertIs(cah.host_online("100.68.142.13"), True)   # self IP

    def test_case_and_fqdn_matching(self):
        with patch.object(cah.subprocess, "run",
                          return_value=proc(0, json.dumps(ts_status_doc()))):
            self.assertIs(cah.host_online("TONY-MACBOOK"), False)
            self.assertIs(
                cah.host_online("tony-macbook.taila0626a.ts.net."), False)

    def test_unknown_peer_and_empty_fail_open(self):
        with patch.object(cah.subprocess, "run",
                          return_value=proc(0, json.dumps(ts_status_doc()))):
            self.assertIsNone(cah.host_online("ghost-host"))
            self.assertIsNone(cah.host_online(""))
            self.assertIsNone(cah.host_online(None))

    def test_tailscale_unusable_fails_open(self):
        for bad in (proc(1, "", "boom"), proc(0, "not json", "")):
            cah._TS_PROBED = False
            cah._TS_PEERS = None
            with patch.object(cah.subprocess, "run", return_value=bad):
                self.assertIsNone(cah.host_online("tony-macbook"))
        cah._TS_PROBED = False
        cah._TS_PEERS = None
        with patch.object(cah.subprocess, "run",
                          side_effect=OSError("no tailscale")):
            self.assertIsNone(cah.host_online("tony-macbook"))

    def test_peer_without_online_key_is_unknown(self):
        doc = ts_status_doc()
        del doc["Peer"]["nodekey:a"]["Online"]
        with patch.object(cah.subprocess, "run",
                          return_value=proc(0, json.dumps(doc))):
            self.assertIsNone(cah.host_online("tony-macbook"))
            self.assertIs(cah.host_online("tony-omen"), True)


def stale_cfg(**kw):
    cfg = {"_slug": "nest-tony-macbook", "enabled": True,
           "interval_min": 15, "last_status": "ok",
           "last_run": OLD_ISO, "host": "tony-macbook"}
    cfg.update(kw)
    return cfg


class HostGateTest(unittest.TestCase):
    def test_stale_demoted_only_when_host_confirmed_offline(self):
        cfg = stale_cfg()
        state, reason = cah.judge(cfg, NOW)
        self.assertEqual(state, "stale")
        with patch.object(cah, "host_online", return_value=False):
            state, reason = cah.host_gate(state, reason, cfg)
            self.assertEqual(state, "host-down")
            self.assertIn("offline", reason)
        for online in (True, None):
            with patch.object(cah, "host_online", return_value=online):
                state, _ = cah.judge(cfg, NOW)
                state, _ = cah.host_gate(state, "r", cfg)
                self.assertEqual(state, "stale")

    def test_gate_needs_host_field(self):
        cfg = stale_cfg()
        del cfg["host"]
        state, _ = cah.judge(cfg, NOW)
        with patch.object(cah, "host_online", return_value=False) as m:
            state, _ = cah.host_gate(state, "r", cfg)
            self.assertEqual(state, "stale")
            m.assert_not_called()

    def test_healthy_states_untouched(self):
        ok_cfg = stale_cfg(last_run=time.time())
        with patch.object(cah, "host_online", return_value=False):
            for cfg, want in ((ok_cfg, "ok"),
                              (stale_cfg(interval_min=0), "manual")):
                state, reason = cah.judge(cfg, NOW)
                self.assertEqual(cah.host_gate(state, reason, cfg),
                                 (want, reason))

    def test_error_and_dead_demoted_too(self):
        err_cfg = stale_cfg(last_status="error", last_error="boom")
        state, reason = cah.judge(err_cfg, NOW)
        self.assertEqual(state, "error")
        dead_cfg = stale_cfg()
        del dead_cfg["last_run"]
        state, _ = cah.judge(dead_cfg, NOW)
        self.assertEqual(state, "dead")
        with patch.object(cah, "host_online", return_value=False):
            for cfg, judged in ((err_cfg, "error"), (dead_cfg, "dead")):
                s, r = cah.judge(cfg, NOW)
                self.assertEqual(s, judged)
                self.assertEqual(cah.host_gate(s, r, cfg)[0], "host-down")

    def test_unparseable_registry_never_gated(self):
        # list_automations can't parse a broken doc, so it carries no
        # 'host' — the gate must leave the 'dead' verdict alone.
        cfg = {"_slug": "x", "_unparseable": True}
        state, reason = cah.judge(cfg, NOW)
        self.assertEqual(state, "dead")
        with patch.object(cah, "host_online", return_value=False):
            self.assertEqual(cah.host_gate(state, reason, cfg)[0], "dead")


class MainLoopTest(unittest.TestCase):
    """End-to-end: one stale nest cfg through main() with CARDS/MDBB
    stubbed — offline host must not card; online host must; an open
    review card auto-closes on the host-down streak."""

    SLUG = "nest-tony-macbook"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cards = Path(self.tmp.name)
        self._patches = [
            patch.object(cah, "CARDS", self.cards),
            patch.object(cah, "list_automations",
                         return_value=[stale_cfg()]),
            patch.object(cah, "page_freshness", return_value={}),
            patch.object(cah, "page_ts_for", return_value=None),
        ]
        for p in self._patches:
            p.start()
        cah._TS_PROBED = False
        cah._TS_PEERS = None

    def tearDown(self):
        for p in self._patches:
            p.stop()
        cah._TS_PROBED = False
        cah._TS_PEERS = None
        self.tmp.cleanup()

    def _card_file(self):
        return self.cards / f"cms-auto-{self.SLUG}.yml"

    def test_offline_host_creates_no_card(self):
        with patch.object(cah, "host_online", return_value=False):
            cah.main()
        self.assertFalse(self._card_file().exists())

    def test_online_host_still_cards(self):
        with patch.object(cah, "host_online", return_value=True):
            cah.main()
        card = cah.yaml.safe_load(self._card_file().read_text())
        self.assertEqual(card["column"], "review")
        self.assertEqual(card["generated"], "cms-auto-health")

    def test_unknown_reachability_fails_open(self):
        with patch.object(cah, "host_online", return_value=None):
            cah.main()
        self.assertTrue(self._card_file().exists())

    def test_offline_host_autoclose_existing_review_card(self):
        self._card_file().write_text(cah.yaml.safe_dump({
            "id": f"cms-auto-{self.SLUG}", "column": "review",
            "generated": "cms-auto-health", "ok_streak": 1,
            "updated": "2026-11-20"}))
        with patch.object(cah, "host_online", return_value=False):
            cah.main()
        card = cah.yaml.safe_load(self._card_file().read_text())
        self.assertEqual(card["column"], "done")
        self.assertIn("offline", card["note"])
        self.assertNotIn("ok_streak", card)


if __name__ == "__main__":
    unittest.main()
