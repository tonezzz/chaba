"""Tests for the launchd task-runtime seam (card
kk-mac-launchd-runner-port): runner-agent must serve the same
transient-unit contract on macOS — launchctl bootstrap/print instead of
systemd-run, a generated plist + bash wrapper supplying the watchdog
bound, the pgrp record and the durable .code exit file, and a
`sysctl vm.loadavg` overload gate — while the systemd path keeps its
exact existing behavior.

Every test runs on Linux: `sh` is stubbed and module runtime state is
forced, so no launchctl/systemctl binary is needed.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"
sys.path.insert(0, str(REPO / "scripts" / "board"))


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent_ld", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


class LaunchdBase(unittest.TestCase):
    """Force the launchd runtime with a sandboxed state dir; `sh` is a
    recording stub each test re-programs via self.sh_fn."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self.m = m
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self._saved = {k: getattr(m, k) for k in ("_RT", "STATE_DIR", "sh")}
        self.addCleanup(self._restore)
        m._RT = "launchd"
        m.STATE_DIR = Path(self.td.name) / "state"
        self.calls = []
        self.sh_fn = lambda argv, **kw: _proc(0)

        def _sh(argv, **kw):
            self.calls.append(argv)
            return self.sh_fn(argv, **kw)

        m.sh = _sh

    def _restore(self):
        for k, v in self._saved.items():
            setattr(self.m, k, v)

    def patch(self, name, value):
        """Set a module attr with restore on cleanup."""
        self._saved[name] = getattr(self.m, name)
        setattr(self.m, name, value)

    def argvs(self, *needle):
        return [a for a in self.calls
                if all(n in " ".join(a) for n in needle)]


class RuntimeDetectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        self._rt = self.mod._RT
        self.mod._RT = None
        self._env = dict(os.environ)

    def tearDown(self):
        self.mod._RT = self._rt
        os.environ.clear()
        os.environ.update(self._env)

    def test_env_override_wins(self):
        os.environ["RUNNER_TASK_RUNTIME"] = "launchd"
        self.assertEqual(self.mod.task_runtime(), "launchd")
        os.environ["RUNNER_TASK_RUNTIME"] = "systemd"
        self.mod._RT = None
        self.assertEqual(self.mod.task_runtime(), "systemd")

    def test_auto_on_this_host_is_systemd(self):
        os.environ.pop("RUNNER_TASK_RUNTIME", None)
        # dev host is Linux with systemctl — auto resolves systemd
        self.assertEqual(self.mod.task_runtime(), "systemd")

    def test_auto_darwin_prefers_launchd(self):
        os.environ.pop("RUNNER_TASK_RUNTIME", None)
        _sw = self.mod.shutil_which
        self.mod.shutil_which = lambda b: f"/usr/bin/{b}"
        try:
            with mock.patch.object(sys, "platform", "darwin"):
                self.assertEqual(self.mod._detect_runtime(), "launchd")
        finally:
            self.mod.shutil_which = _sw


class LaunchTest(LaunchdBase):
    def test_writes_wrapper_plist_and_bootstraps(self):
        self.sh_fn = lambda argv, **kw: (
            _proc(0) if argv[:2] == ["plutil", "-lint"]
            else _proc(1) if argv[:2] == ["launchctl", "print"]
            else _proc(0))
        err = self.m.rt_launch("runner-c1-1", "runner c1",
                               "echo $$HOME; exit 0",
                               timeout_s=120, env={"FOO": "bar"})
        self.assertEqual(err, "")
        # bootstrap argv — the gui/<uid> domain from the card contract
        boots = self.argvs("launchctl", "bootstrap")
        self.assertEqual(len(boots), 1)
        self.assertEqual(boots[0][2], f"gui/{os.getuid()}")
        plist = Path(boots[0][3])
        self.assertTrue(plist.is_file())
        # no stale-registration bootout needed (print failed first)
        self.assertEqual(self.argvs("bootout"), [])
        px = plist.read_text()
        self.assertIn("<string>runner-c1-1</string>", px)
        self.assertIn("<key>RunAtLoad</key>", px)
        self.assertIn("<string>Background</string>", px)
        self.assertIn("<key>FOO</key>", px)
        self.assertIn("<string>bar</string>", px)
        self.assertIn("<key>HOME</key>", px)
        self.assertIn("<key>StandardOutPath</key>", px)
        wrapper = plist.parent / "runner-c1-1.sh"
        self.assertTrue(wrapper.is_file())
        wx = wrapper.read_text()
        # the $$ -> $ de-escape (systemd ExecStart form -> literal bash)
        self.assertIn("echo $HOME", wx)
        self.assertNotIn("$$HOME", wx)
        # the watchdog bound, the pgrp record, the orphan trap and the
        # durable exit-code write — the systemd-run contract pieces
        self.assertIn("set -m", wx)
        self.assertIn("sleep 120", wx)
        self.assertIn("kill -TERM", wx)
        self.assertIn("kill -KILL", wx)
        self.assertIn("trap", wx)
        self.assertIn("runner-c1-1.pid", wx)
        self.assertIn("runner-c1-1.code", wx)

    def test_stale_registration_rebootstrapped(self):
        def _sh(argv, **kw):
            if argv[:2] == ["launchctl", "print"]:
                return _proc(0, "state = not running\n")
            return _proc(0)
        self.sh_fn = _sh
        err = self.m.rt_launch("runner-c9-1", "d", "true")
        self.assertEqual(err, "")
        self.assertEqual(len(self.argvs("bootout")), 1)
        self.assertEqual(len(self.argvs("bootstrap")), 1)

    def test_running_job_refused(self):
        def _sh(argv, **kw):
            if argv[:2] == ["launchctl", "print"]:
                return _proc(0, "state = running\npid = 4242\n")
            return _proc(0)
        self.sh_fn = _sh
        err = self.m.rt_launch("runner-c9-1", "d", "true")
        self.assertIn("already running", err)
        self.assertEqual(self.argvs("bootstrap"), [])

    def test_plist_lint_failure_reported(self):
        self.sh_fn = lambda argv, **kw: _proc(1, err="bad plist")
        err = self.m.rt_launch("runner-c9-1", "d", "true")
        self.assertIn("plist invalid", err)
        self.assertEqual(self.argvs("bootstrap"), [])

    def test_bootstrap_error_returned(self):
        def _sh(argv, **kw):
            if argv[:2] == ["launchctl", "bootstrap"]:
                return _proc(5, err="Bootstrap failed: 5")
            if argv[:2] == ["launchctl", "print"]:
                return _proc(1)
            return _proc(0)
        self.sh_fn = _sh
        self.assertIn("Bootstrap failed", self.m.rt_launch("u", "d", "true"))

    def test_domain_override(self):
        with mock.patch.dict(os.environ, {"RUNNER_LAUNCHD_DOMAIN": "user"}):
            self.assertEqual(self.m._launchd_domain(),
                             f"user/{os.getuid()}")

    def test_systemd_argv_unchanged(self):
        """the systemd arm of rt_launch builds the historical argv."""
        self.patch("_RT", "systemd")
        self.patch("task_run_props", lambda: ["--property=Nice=10"])
        err = self.m.rt_launch("runner-x-1", "desc", "echo hi",
                               timeout_s=60, env={"K": "V"})
        self.assertEqual(err, "")
        argv = self.calls[-1]
        self.assertEqual(argv[:4],
                         ["systemd-run", "--user", "--unit=runner-x-1",
                          "--collect"])
        self.assertIn("--property=RuntimeMaxSec=60", argv)
        self.assertIn("--property=Nice=10", argv)
        self.assertIn("--setenv", argv)
        self.assertIn("K=V", argv)
        self.assertEqual(argv[-2:], ["-lc", "echo hi"])


class ActiveTest(LaunchdBase):
    def test_running_via_pid(self):
        self.sh_fn = lambda argv, **kw: _proc(
            0, "gui/501/x = {\n\tstate = running\n\tpid = 1234\n}")
        self.assertTrue(self.m.unit_active("runner-x-1"))

    def test_running_via_state(self):
        self.sh_fn = lambda argv, **kw: _proc(
            0, "gui/501/x = {\n\tstate = running\n}")
        self.assertTrue(self.m.unit_active("runner-x-1"))

    def test_not_running(self):
        self.sh_fn = lambda argv, **kw: _proc(0, "\tstate = not running\n")
        self.assertFalse(self.m.unit_active("runner-x-1"))

    def test_unregistered(self):
        self.sh_fn = lambda argv, **kw: _proc(
            113, err="Could not find service")
        self.assertFalse(self.m.unit_active("runner-x-1"))


class CollectTest(LaunchdBase):
    def _taskdir(self, name):
        home = Path(self.td.name) / "home"
        p = home / ".local/share/devin-dispatch/tasks" / name
        p.mkdir(parents=True, exist_ok=True)
        return p, home

    def test_devin_taskdir_exit_code_wins(self):
        td, home = self._taskdir("card1-999")
        (td / "exit_code").write_text("0\n")
        with mock.patch.object(Path, "home", return_value=home):
            ok, res = self.m.collect("devin-task-card1-999")
        self.assertTrue(ok)
        self.assertIn("exit=0", res)

    def test_devin_taskdir_nonzero(self):
        td, home = self._taskdir("card1-999")
        (td / "exit_code").write_text("23\n")
        with mock.patch.object(Path, "home", return_value=home):
            ok, res = self.m.collect("devin-task-card1-999")
        self.assertFalse(ok)
        self.assertIn("exit=23", res)

    def test_code_file_for_runner_unit(self):
        (self.m.STATE_DIR / "exit").mkdir(parents=True)
        code = self.m.STATE_DIR / "exit" / "runner-c1-1.code"
        code.write_text("0\n")
        ok, res = self.m.collect("runner-c1-1")
        self.assertTrue(ok)
        self.assertIn("exit=0", res)
        self.assertFalse(code.exists())  # consumed
        self.assertEqual(len(self.argvs("bootout")), 1)  # gc'd

    def test_code_file_nonzero(self):
        (self.m.STATE_DIR / "exit").mkdir(parents=True)
        (self.m.STATE_DIR / "exit" / "runner-c1-1.code").write_text("1\n")
        ok, res = self.m.collect("runner-c1-1")
        self.assertFalse(ok)

    def test_last_exit_code_fallback(self):
        def _sh(argv, **kw):
            if argv[:2] == ["launchctl", "print"]:
                return _proc(0, "state = not running\n"
                               "last exit code = 0\n")
            return _proc(0)
        self.sh_fn = _sh
        ok, res = self.m.collect("runner-c1-1")
        self.assertTrue(ok)
        self.assertIn("exit=0", res)
        self.assertEqual(len(self.argvs("bootout")), 1)

    def test_no_record_is_not_ok(self):
        """unregistered + no files -> unproven, never ok."""
        self.sh_fn = lambda argv, **kw: _proc(113, err="not found")
        ok, res = self.m.collect("devin-task-ghost-1")
        self.assertFalse(ok)
        self.assertIn("unproven", res)

    def test_log_tail_in_result(self):
        logs = self.m.STATE_DIR / "logs"
        logs.mkdir(parents=True)
        (logs / "runner-c1-1.log").write_text(
            "line one\nfinal line\n")
        (self.m.STATE_DIR / "exit").mkdir(parents=True)
        (self.m.STATE_DIR / "exit" / "runner-c1-1.code").write_text("0\n")
        ok, res = self.m.collect("runner-c1-1")
        self.assertTrue(ok)
        self.assertIn("final line", res)


class PidsAndSignalTest(LaunchdBase):
    def test_pids_from_pgrp_file(self):
        ldir = self.m.STATE_DIR / "launchd"
        ldir.mkdir(parents=True)
        (ldir / "runner-c1-1.pid").write_text("777\n")
        self.sh_fn = lambda argv, **kw: (
            _proc(0, "777\n778\n") if argv[:2] == ["pgrep", "-g"]
            else _proc(0))
        self.assertEqual(self.m.unit_pids("runner-c1-1"), ["777", "778"])

    def test_pids_fallback_launchctl_pid(self):
        self.sh_fn = lambda argv, **kw: _proc(
            0, "state = running\npid = 555\n")
        self.assertEqual(self.m.unit_pids("runner-c1-1"), ["555"])

    def test_signal_targets_pgrp(self):
        ldir = self.m.STATE_DIR / "launchd"
        ldir.mkdir(parents=True)
        (ldir / "runner-c1-1.pid").write_text("777\n")
        self.m._signal_job("runner-c1-1", "SIGSTOP")
        self.assertEqual(self.calls[-1],
                         ["kill", "-SIGSTOP", "-777"])

    def test_resume_hint_uses_pgrp_file(self):
        hint = self.m._resume_hint("runner-c1-1")
        self.assertIn("kill -CONT", hint)
        self.assertIn("runner-c1-1.pid", hint)


class UnitsForCardTest(LaunchdBase):
    def test_glob_and_registered_scrape(self):
        ldir = self.m.STATE_DIR / "launchd"
        ldir.mkdir(parents=True)
        (ldir / "devin-task-card1-111.plist").write_text("x")
        (ldir / "devin-task-other-222.plist").write_text("x")
        self.sh_fn = lambda argv, **kw: _proc(
            0, "services = {\n\tdevin-task-card1-333\n}")
        got = self.m.units_for_card("card1")
        self.assertEqual(sorted(got),
                         ["devin-task-card1-111", "devin-task-card1-333"])


class LoadGateTest(LaunchdBase):
    def test_sysctl_loadavg_parsed(self):
        self.sh_fn = lambda argv, **kw: (
            _proc(0, "{ 1.90 2.55 3.10 }\n") if argv[:2] == [
                "sysctl", "-n"] else _proc(0))
        self.assertAlmostEqual(self.m._sysctl_load5(), 2.55)
        self.assertEqual(self.calls[-1][:3],
                         ["sysctl", "-n", "vm.loadavg"])

    def test_overloaded_uses_load5_per_core(self):
        self.patch("_load5_per_core", lambda: 1.4)
        self.assertTrue(self.m.overloaded())
        self.assertFalse(self.m.overloaded(2.0))  # script ceiling

    def test_unparseable_loadavg_falls_back(self):
        self.sh_fn = lambda argv, **kw: _proc(0, "garbage\n")
        self.assertIsNone(self.m._sysctl_load5())


class ClaimableDevinGateTest(LaunchdBase):
    """the devin executor path is systemd-only — a launchd runner must
    decline what it can't serve so the card stays queued for Linux."""

    def _card(self, **action):
        a = {"type": "dispatch", "status": "queued"}
        a.update(action)
        return {"id": "c-gate", "title": "c", "action": a}

    def setUp(self):
        super().setUp()
        self.patch("LABELS", set())
        self.patch("push_capable", lambda repo: True)

    def test_devin_executor_declined_on_launchd(self):
        self.patch("OPENCODE_LANES", False)
        typ, why = self.m._claimable(
            self._card(executor="devin", repo="chaba"))
        self.assertEqual(typ, "")
        self.assertIn("systemd-only", why)

    def test_unexecutor_card_without_oc_route_declined(self):
        self.patch("OPENCODE_LANES", False)
        self.patch("classify_lane", lambda card: "devin")
        typ, why = self.m._claimable(self._card(repo="chaba"))
        self.assertEqual(typ, "")
        self.assertIn("systemd-only", why)

    def test_unexecutor_card_with_oc_route_serves(self):
        m = self.m
        self.patch("OPENCODE_LANES", True)
        self.patch("opencode_bin", lambda: "/fake/opencode")
        self.patch("classify_lane", lambda card: "free_lane")
        self.patch("card_profile", lambda card: "ops-readonly")
        self.patch("LANE_MODELS", {"free_lane": "litellm/x"})
        typ, why = m._claimable(self._card(repo="chaba"))
        self.assertEqual(typ, "dispatch")
        self.assertEqual(why, "")


class WrapperContentsTest(LaunchdBase):
    def test_limits_arm_ulimit(self):
        self.patch("LIMITS_ON", True)
        self.patch("TASK_MEM_MAX", "8G")
        wx = self.m._launchd_wrapper("u", "true", 0)
        self.assertIn("ulimit -v 8388608", wx)

    def test_no_ulimit_without_limits(self):
        self.patch("LIMITS_ON", False)
        wx = self.m._launchd_wrapper("u", "true", 0)
        self.assertNotIn("ulimit", wx)

    def test_mem_kb_parse(self):
        self.assertEqual(self.m._mem_kb("8G"), 8388608)
        self.assertEqual(self.m._mem_kb("512M"), 524288)
        self.assertEqual(self.m._mem_kb(""), 0)


if __name__ == "__main__":
    unittest.main()
