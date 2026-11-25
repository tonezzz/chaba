"""Unit tests for scripts/ada/scenario-provider-gate.py — the live
/backend probe added for card provider-gate-zombie-backend-blind
(2026-11-02: ada-dev sat systemd-active with zero journal output all
day — a zombie uvicorn — and the gate still verdict 'ok', so every
scenario failed in ~0.4s).

Covers: service_port resolution (ADA_PORT env -> --port ExecStart ->
''), check_live_probe verdicts (ok / infra / skip), and the main()
verdict chain — an active-but-not-serving unit must gate 'infra'.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ada" / "scenario-provider-gate.py"

spec = importlib.util.spec_from_file_location("scenario_provider_gate",
                                              SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class FakeResp:
    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode())

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def sh_router(env_out="", cat_out=""):
    """_sh stand-in keyed on the systemctl subcommand."""
    def _fake(args, timeout=40):
        if "show" in args:
            return env_out
        if "cat" in args:
            return cat_out
        return ""
    return _fake


class ServicePortTests(unittest.TestCase):
    def test_ada_port_env_wins(self):
        with patch.object(gate, "_sh", sh_router(
                env_out="HOME=/home/x ADA_PORT=8005 OTHER=1")):
            self.assertEqual(gate.service_port("ada-dev"), "8005")

    def test_port_flag_fallback(self):
        with patch.object(gate, "_sh", sh_router(
                cat_out="ExecStart=/usr/bin/uvicorn pwa_server:app "
                        "--host 127.0.0.1 --port 8002")):
            self.assertEqual(gate.service_port("ada-ha-tony"), "8002")

    def test_unresolvable_returns_empty(self):
        with patch.object(gate, "_sh", sh_router()):
            self.assertEqual(gate.service_port("ada-tg-relay"), "")


class LiveProbeTests(unittest.TestCase):
    def test_ok_on_health_200(self):
        with patch.object(gate, "_sh",
                          sh_router(env_out="ADA_PORT=8005")), \
             patch("urllib.request.urlopen",
                   return_value=FakeResp({"ok": True,
                                          "active_sessions": 0})):
            status, detail = gate.check_live_probe("ada-dev")
        self.assertEqual(status, "ok")
        self.assertIn("ok:true", detail)

    def test_infra_on_connect_refused(self):
        import urllib.error
        with patch.object(gate, "_sh",
                          sh_router(env_out="ADA_PORT=8005")), \
             patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("refused")), \
             patch("time.sleep"):
            status, detail = gate.check_live_probe("ada-dev")
        self.assertEqual(status, "infra")
        self.assertIn("zombie", detail)

    def test_infra_on_ok_false(self):
        with patch.object(gate, "_sh",
                          sh_router(env_out="ADA_PORT=8005")), \
             patch("urllib.request.urlopen",
                   return_value=FakeResp({"ok": False})), \
             patch("time.sleep"):
            status, _ = gate.check_live_probe("ada-dev")
        self.assertEqual(status, "infra")

    def test_skip_when_no_port(self):
        with patch.object(gate, "_sh", sh_router()):
            status, detail = gate.check_live_probe("ada-tg-relay")
        self.assertEqual(status, "skip")
        self.assertIn("no ADA_PORT", detail)


class VerdictTests(unittest.TestCase):
    """main() end-to-end with every probe stubbed — the zombie case."""

    def _run(self, live):
        argv = ["scenario-provider-gate.py", "--unit", "ada-dev",
                "--dry-run"]
        with patch.object(sys, "argv", argv), \
             patch.object(gate, "check_unit_active",
                          return_value=(True, "active")), \
             patch.object(gate, "check_live_probe",
                          return_value=live), \
             patch.object(gate, "check_free_lane",
                          return_value=("ok", "live key = free lane")), \
             patch.object(gate, "check_paid_allow", return_value=""), \
             patch.object(gate, "check_quota",
                          return_value=("ok", {"journal_lines": 1,
                                               "healthy_markers": 0,
                                               "rest_served": 0})), \
             patch.object(gate, "churn_scan", return_value={}):
            return gate.main()

    def test_zombie_backend_gates_infra(self):
        # the 2026-11-02 evidence shape: active + silent journal +
        # health probe dead -> infra, exit 1 (clean skip)
        self.assertEqual(
            self._run(("infra", "backend not serving "
                              "(http://127.0.0.1:8005/api/health "
                              "refused) — zombie unit?")), 1)

    def test_serving_backend_proceeds(self):
        self.assertEqual(
            self._run(("ok", "http://127.0.0.1:8005/api/health "
                            "ok:true (sessions=0)")), 0)


if __name__ == "__main__":
    unittest.main()
