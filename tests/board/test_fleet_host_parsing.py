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
        keys = [key for key, _ in violations]
        self.assertNotIn("devin-cli", keys)
        self.assertNotIn("devin-dispatch", keys)

    def test_repo_checkout_alert_names_measured_base(self):
        # con01 2026-11-26: repos.conf declares mddb-fork=main, the
        # checkout sat on feat/vector-algorithms at that branch's tip.
        # The alert wrongly said "601 behind origin/feat/vector-algorithms"
        # because judge() named the checkout branch instead of the ref it
        # actually measured. Report both, with the measured ref first.
        probe = {
            "git_ok": True,
            "runner_env": {"RUNNER_LABELS": "push:chaba"},
            "repos": {"mddb-fork": {
                "exists": True, "has_git": True,
                "path": "/home/tony/CascadeProjects/mddb-fork",
                "behind": 601,
                "base": "origin/main",
                "head_branch": "feat/vector-algorithms",
                "remote": "git@github.com:tonezzz/mddb-fork.git",
                "push_probe": False, "push_probe_err": "no deploy key",
            }},
            "installed": {},
            "tool_pins": {"ok": True, "tools": {}},
            "dispatch_repos": {"resolved_dir": "/tmp/x", "import_ok": True,
                               "missing": []},
            "devin": {},
        }
        violations, _ = fh.judge("con01", probe, {})
        msgs = [m for key, m in violations if key == "repo-checkout"]
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("behind origin/main", msgs[0])
        self.assertIn("checkout is on feat/vector-algorithms", msgs[0])
        self.assertNotIn("origin/feat/vector-algorithms", msgs[0])

    def test_probe_uses_kk_mac_runner_interpreter(self):
        # kk-mac's launchd runner uses /opt/homebrew/bin/python3; the SSH
        # default python3 is 3.9 and cannot import dispatch_repos.py.
        self.assertEqual(fh.probe_python("kk-mac"),
                         "/opt/homebrew/bin/python3")
        self.assertEqual(fh.probe_python("tony-dell"), "python3")

    def test_judge_flags_installed_tool_pin_drift(self):
        # 4af10b4c5c dropped the tool-pin audit entirely; a stale install
        # then looked healthy as long as the host's own checkout agreed.
        probe = {
            "git_ok": True,
            "runner_env": {"RUNNER_LABELS": "push:chaba"},
            "repos": {"chaba": {
                "exists": True, "has_git": True, "behind": 0,
                "remote": "git@github.com:tonezzz/chaba.git",
                "fetch_ok": True, "push_probe": True}},
            "installed": {"runner_agent": {"sha": "deadbeefdeadbeef"}},
            "tool_pins": {
                "ok": True,
                "tools": {"runner_agent": "1514c75c4679a01b",
                          "devin_dispatch": "c5fa39476cb27cad"},
                "checkout": {"runner_agent": "1514c75c4679a01b",
                             "devin_dispatch": "c5fa39476cb27cad"},
            },
            "dispatch_repos": {"resolved_dir": "/tmp/x", "import_ok": True,
                               "missing": []},
            "devin": {"path": "/usr/local/bin/devin"},
        }
        violations, _ = fh.judge("tony-dell", probe, {})
        msgs = [m for key, m in violations if key == "tool-pin"]
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("~/.local/bin/runner-agent sha deadbeefdeadbeef "
                      "!= pin 1514c75c4679a01b", msgs[0])
        self.assertIn("installed build is stale", msgs[0])


if __name__ == "__main__":
    unittest.main()
