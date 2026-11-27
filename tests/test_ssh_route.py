"""Unit tests for scripts/lib/ssh_route.py — the resilient fleet-ssh
runner (card runner-drift-rearm-idc03-ssh-proxyjump-dead).

Pins the contract: direct tailnet (`ProxyJump=none ProxyCommand=none`)
is tried first so a stale/broken ProxyJump in the local ssh config
cannot wedge the caller; the operator's ssh config is the fallback;
all-fail returns the last route's result; a timeout on the last route
propagates.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from ssh_route import ssh_argvs, ssh_run  # noqa: E402


def _res(rc, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=rc,
                                       stdout=out, stderr=err)


class TestSshArgvs(unittest.TestCase):
    def test_direct_route_first_then_config(self):
        argvs = list(ssh_argvs("idc03", "true",
                               opts=["-o", "BatchMode=yes"]))
        self.assertEqual(len(argvs), 2)
        self.assertIn("-o", argvs[0])
        self.assertEqual(argvs[0][argvs[0].index("ProxyJump=none") - 1],
                         "-o")
        self.assertIn("ProxyCommand=none", argvs[0])
        self.assertNotIn("ProxyJump=none", argvs[1])
        for a in argvs:
            self.assertEqual(a[0], "ssh")
            self.assertEqual(a[-2:], ["idc03", "true"])

    def test_remote_list_and_str_both_flatten(self):
        a_str = list(ssh_argvs("h", "uptime"))[0]
        a_list = list(ssh_argvs("h", ["uptime", "-p"]))[0]
        self.assertEqual(a_str[-2:], ["h", "uptime"])
        self.assertEqual(a_list[-3:], ["h", "uptime", "-p"])


class TestSshRun(unittest.TestCase):
    def test_first_success_short_circuits(self):
        with mock.patch("ssh_route.subprocess.run",
                        return_value=_res(0)) as run:
            res = ssh_run("idc03", "true", timeout=5)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(run.call_count, 1)
        # the direct route was used
        self.assertIn("ProxyJump=none", run.call_args.args[0])

    def test_falls_back_to_config_route_on_failure(self):
        with mock.patch("ssh_route.subprocess.run",
                        side_effect=[_res(255, err="prohibited"),
                                     _res(0, out="ok")]) as run:
            res = ssh_run("idc03", "true", timeout=5)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn("ProxyJump=none", run.call_args_list[0].args[0])
        self.assertNotIn("ProxyJump=none",
                         run.call_args_list[1].args[0])

    def test_all_fail_returns_last_route_result(self):
        with mock.patch("ssh_route.subprocess.run",
                        side_effect=[_res(255, err="direct dead"),
                                     _res(1, err="config dead")]) as run:
            res = ssh_run("idc03", "true", timeout=5)
        self.assertEqual(res.returncode, 1)
        self.assertEqual(res.stderr, "config dead")
        self.assertEqual(run.call_count, 2)

    def test_timeout_on_early_route_advances(self):
        with mock.patch("ssh_route.subprocess.run",
                        side_effect=[subprocess.TimeoutExpired("ssh", 5),
                                     _res(0)]) as run:
            res = ssh_run("idc03", "true", timeout=5)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(run.call_count, 2)

    def test_timeout_on_last_route_propagates(self):
        with mock.patch("ssh_route.subprocess.run",
                        side_effect=[_res(255),
                                     subprocess.TimeoutExpired("ssh", 5)]):
            with self.assertRaises(subprocess.TimeoutExpired):
                ssh_run("idc03", "true", timeout=5)

    def test_kwargs_passed_through(self):
        with mock.patch("ssh_route.subprocess.run",
                        return_value=_res(0)) as run:
            ssh_run("idc03", "bash -s",
                    opts=["-o", "ConnectTimeout=8"],
                    input="echo hi", capture_output=True, text=True,
                    timeout=9)
        kw = run.call_args.kwargs
        self.assertEqual(kw["input"], "echo hi")
        self.assertTrue(kw["text"])
        self.assertEqual(kw["timeout"], 9)


if __name__ == "__main__":
    unittest.main()
