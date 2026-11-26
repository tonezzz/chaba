"""OPS-1406: fleet audits must see every declared dispatch host.

The runner_fleet prose in ssot.kanban.yml is the single declaration of
who can claim work. A regex that silently omitted con01 (VPS) or kk-mac
(macOS) made fleet-health blind to them and made host pins look
unsatisfiable at queue time. The devin-cli check is capability-aware:
con01 (script/container only) and kk-mac (devin Linux-only) do not
serve devin, so a missing devin binary is not a bootstrap failure.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
os.environ.setdefault("CHABA_REPO", str(REPO))


def _load(filename: str, module: str):
    spec = importlib.util.spec_from_file_location(
        module, REPO / "scripts" / "board" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fh = _load("runner-fleet-health.py", "runner_fleet_health")
dr = _load("dispatch_repos.py", "dispatch_repos")


class FleetHostParsing(unittest.TestCase):
    def test_health_sees_every_declared_host(self):
        hosts = fh.fleet()
        for host in ("tony-dell", "tony-omen", "idc02", "idc03", "mn01",
                     "con01", "tony-macbook", "kk-mac"):
            self.assertIn(host, hosts, f"{host} omitted by fleet-health")

    def test_dispatch_capabilities_see_con01_and_kk_mac(self):
        caps = dr.fleet_capabilities()
        for host in ("con01", "kk-mac"):
            self.assertIn(host, caps, f"{host} omitted by dispatch_repos")
        self.assertIn("push:chaba", caps["con01"]["labels"])
        self.assertEqual(caps["con01"]["types"], {"script", "container"})

    def test_devin_exemption_is_capability_driven(self):
        self.assertFalse(fh.devin_expected("con01"))
        self.assertFalse(fh.devin_expected("kk-mac"))
        self.assertTrue(fh.devin_expected("tony-dell"))

    def test_judge_does_not_flag_devin_for_con01(self):
        probe = {
            "git_ok": True,
            "runner_env": {"RUNNER_LABELS": "push:chaba"},
            "repos": {"chaba": {
                "exists": True, "has_git": True, "behind": 0,
                "remote": "git@github.com:tonezzz/chaba.git",
                "fetch_ok": True, "push_probe": True}},
            "installed": {},
            "tool_pins": {"ok": True, "tools": {}},
            "dispatch_repos": {"resolved_dir": "/tmp/x", "import_ok": True,
                               "missing": []},
            "devin": {},
        }
        violations, _ = fh.judge("con01", probe, {})
        self.assertNotIn("devin-cli", [key for key, _ in violations])


if __name__ == "__main__":
    unittest.main()
