"""Tests for card OPS-1036 — the scheduled stale dispatch-worktree
sweeper:

  a) dispatch-wt-sweep evidence gate accepts every durable task record
     (meta.json/events.jsonl/usage.json/verdict.json/exit_code), not
     just the original two — and still keeps trees with no evidence.
  b) on_origin fetches once per repo root per sweep run (a host with
     dozens of stale trees on one repo pays one fetch, not N).
  c) unit_active is runtime-aware: darwin checks launchd gui/<uid>
     devin-task-<tid> jobs via launchctl print; missing launchctl
     keeps everything (keep-on-doubt).
  d) runner-agent wt_sweep_pass: stamp-file throttle, module-missing
     no-op, sweep failure warn-only, DISPATCH_WT_SWEEP/RUNNER_WT_SWEEP=0
     disables.

No network, no systemd/launchd — git ops stay inside tmpdirs, sh and
module resolution are stubbed.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))


def _load(name: str, script: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "board" / script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True)


TID = "20990102-000000-ops1036"
BRANCH = f"dispatch/{TID}"


class SweepGateTest(unittest.TestCase):
    """(a)+(b) evidence breadth + fetch dedup on real tmpdir worktrees."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("dispatch_wt_sweep_g", "dispatch-wt-sweep.py")

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._env = {k: os.environ.get(k) for k in ("BOARD_API", "RUNNER_API",
                                                  "DISPATCH_WT_SWEEP")}
        os.environ["BOARD_API"] = "http://127.0.0.1:9"
        os.environ.pop("DISPATCH_WT_SWEEP", None)

        self.origin = self.tmp / "origin.git"
        self.origin.mkdir()
        r = subprocess.run(["git", "init", "-q", "--bare", "-b",
                            "master", str(self.origin)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        seed = self.tmp / "seed"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(seed)], capture_output=True)
        (seed / "file.txt").write_text("base\n")
        git(seed, "add", "file.txt")
        git(seed, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "base")
        assert git(seed, "push", "-q", "-u", "origin", "master").returncode == 0

        self.repo = self.tmp / "runner-repo"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(self.repo)], capture_output=True)
        self.base = self.tmp / "worktrees"
        self.base.mkdir()
        self.tasks = self.tmp / "tasks"
        self.tasks.mkdir()

        self._saved_unit = self.mod.unit_active
        self._saved_note = self.mod.note_salvage
        self._saved_sh = self.mod.sh
        self.mod.unit_active = lambda tid: False
        self.mod.note_salvage = lambda cid, text: None
        # count origin fetches without breaking the real git calls
        self.fetches = []
        real_sh = self.mod.sh

        def counting_sh(args, timeout=30):
            if "fetch" in args:
                self.fetches.append(list(args))
            return real_sh(args, timeout=timeout)
        self.mod.sh = counting_sh

    def tearDown(self):
        self.mod.unit_active = self._saved_unit
        self.mod.note_salvage = self._saved_note
        self.mod.sh = self._saved_sh
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    def _mk_wt(self, tid: str) -> Path:
        wt = self.base / f"dispatch-wt-{tid}"
        r = git(self.repo, "worktree", "add", "-q", str(wt),
                "-b", f"dispatch/{tid}", "origin/master")
        assert r.returncode == 0, r.stderr
        return wt

    def _sweep(self, apply: bool = True) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.mod.sweep(self.base, 0.0, self.tasks, apply)
        return buf.getvalue()

    def test_evidence_files_accepted(self):
        for i, fname in enumerate(
                ("usage.json", "verdict.json", "exit_code")):
            tid = f"{TID}-{i}"
            wt = self._mk_wt(tid)
            tdir = self.tasks / tid
            tdir.mkdir(parents=True)
            (tdir / fname).write_text("{}")
            out = self._sweep()
            self.assertFalse(wt.is_dir(),
                             f"{fname}: {out}")

    def test_no_evidence_keeps(self):
        tid = f"{TID}-noev"
        wt = self._mk_wt(tid)
        out = self._sweep()
        self.assertIn("KEEP", out)
        self.assertTrue(wt.is_dir())

    def test_fetch_once_per_repo(self):
        tids = [f"{TID}-f{i}" for i in range(3)]
        wts = [self._mk_wt(t) for t in tids]
        for tid in tids:
            tdir = self.tasks / tid
            tdir.mkdir(parents=True)
            (tdir / "meta.json").write_text("{}")
        out = self._sweep()
        for wt in wts:
            self.assertFalse(wt.is_dir(), out)
        # one repo root -> exactly one `git fetch` across all three trees
        self.assertEqual(len(self.fetches), 1, self.fetches)

    def test_kill_switch(self):
        tid = f"{TID}-off"
        wt = self._mk_wt(tid)
        tdir = self.tasks / tid
        tdir.mkdir(parents=True)
        (tdir / "meta.json").write_text("{}")
        os.environ["DISPATCH_WT_SWEEP"] = "0"
        out = self._sweep()
        self.assertIn("disabled", out)
        self.assertTrue(wt.is_dir())


class LaunchdActiveTest(unittest.TestCase):
    """(c) darwin branch of unit_active."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("dispatch_wt_sweep_l", "dispatch-wt-sweep.py")

    def setUp(self):
        self._saved_sh = self.mod.sh
        self._saved_which = self.mod.shutil.which
        self.calls = []

        def fake_sh(args, timeout=30):
            self.calls.append(list(args))
            return self._responder(args)
        self.mod.sh = fake_sh

    def tearDown(self):
        self.mod.sh = self._saved_sh
        self.mod.shutil.which = self._saved_which

    def _responder(self, args):
        return _proc(rc=1)

    def test_darwin_no_launchctl_keeps(self):
        self.mod.shutil.which = lambda name: None
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertTrue(self.mod.unit_active("sometid"))

    def test_darwin_running_job_active(self):
        self.mod.shutil.which = lambda name: "/usr/bin/launchctl"

        def resp(args):
            if args[:2] == ["launchctl", "print"]:
                return _proc(rc=0, out="\tstate = running\n\tpid = 4242\n")
            return _proc(rc=1)
        self._responder = resp
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertTrue(self.mod.unit_active("sometid"))
        self.assertTrue(any(c[:2] == ["launchctl", "print"]
                            for c in self.calls))

    def test_darwin_finished_job_not_active(self):
        self.mod.shutil.which = lambda name: "/usr/bin/launchctl"

        def resp(args):
            if args[:2] == ["launchctl", "print"]:
                return _proc(rc=0, out="\tstate = not running\n")
            return _proc(rc=1)
        self._responder = resp
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertFalse(self.mod.unit_active("sometid"))

    def test_darwin_fuN_plist_candidate(self):
        # a -fuN followup plist under the launchd state dir must be
        # probed even when the base job is gone
        self.mod.shutil.which = lambda name: "/usr/bin/launchctl"
        home = Path(tempfile.mkdtemp())
        ldir = home / ".local/share/runner-agent/launchd"
        ldir.mkdir(parents=True)
        (ldir / "devin-task-tid1-fu2.plist").write_text("<plist/>")
        seen = []

        def resp(args):
            seen.append(args[-1])
            if args[-1].endswith("devin-task-tid1-fu2"):
                return _proc(rc=0, out="\tpid = 7\n")
            return _proc(rc=1)
        self._responder = resp
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(Path, "home", return_value=home):
            self.assertTrue(self.mod.unit_active("tid1"))
        self.assertTrue(any(t.endswith("devin-task-tid1-fu2")
                            for t in seen), seen)


class RunnerWtSweepPassTest(unittest.TestCase):
    """(d) runner-agent wt_sweep_pass throttle + failure isolation."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("runner_agent_ws", "runner-agent.py")

    def setUp(self):
        m = self.mod
        self.m = m
        self._saved = {k: getattr(m, k) for k in (
            "WT_SWEEP", "WT_SWEEP_S", "WT_SWEEP_DAYS",
            "WT_SWEEP_STAMP", "STATE_DIR")}
        self._td = tempfile.TemporaryDirectory()
        m.STATE_DIR = Path(self._td.name)
        m.WT_SWEEP_STAMP = m.STATE_DIR / "wt-sweep.ts"
        m.WT_SWEEP = True
        m.WT_SWEEP_S = 3600
        m.WT_SWEEP_DAYS = 3.0
        self.calls = []
        self._saved_mod = m.wt_sweep_module
        fake = types.SimpleNamespace(
            sweep=lambda base, days, tr, apply_: self.calls.append(
                (base, days, tr, apply_)) or 0)
        m.wt_sweep_module = lambda: fake

    def tearDown(self):
        m = self.m
        for k, v in self._saved.items():
            setattr(m, k, v)
        m.wt_sweep_module = self._saved_mod
        self._td.cleanup()

    def test_runs_when_stamp_absent(self):
        self.m.wt_sweep_pass()
        self.assertEqual(len(self.calls), 1)
        base, days, tr, apply_ = self.calls[0]
        self.assertEqual(base, Path.home() / "CascadeProjects")
        self.assertEqual(days, 3.0)
        self.assertIsNone(tr)
        self.assertTrue(apply_)
        self.assertTrue(self.m.WT_SWEEP_STAMP.exists())

    def test_throttled_by_fresh_stamp(self):
        self.m.wt_sweep_pass()
        self.m.wt_sweep_pass()
        self.assertEqual(len(self.calls), 1)

    def test_runs_again_after_interval(self):
        self.m.WT_SWEEP_STAMP.write_text(str(time.time() - 7200))
        self.m.wt_sweep_pass()
        self.assertEqual(len(self.calls), 1)

    def test_disabled(self):
        self.m.WT_SWEEP = False
        self.m.wt_sweep_pass()
        self.assertEqual(self.calls, [])
        self.m.WT_SWEEP = True
        self.m.WT_SWEEP_S = 0
        self.m.wt_sweep_pass()
        self.assertEqual(self.calls, [])

    def test_module_missing_is_noop(self):
        self.m.wt_sweep_module = lambda: None
        self.m.wt_sweep_pass()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.m.WT_SWEEP_STAMP.exists())

    def test_sweep_failure_warns_and_stamps(self):
        def boom(*a):
            raise RuntimeError("git exploded")
        self.m.wt_sweep_module = lambda: types.SimpleNamespace(
            sweep=boom)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.m.wt_sweep_pass()
        self.assertIn("wt-sweep failed", buf.getvalue())
        self.assertTrue(self.m.WT_SWEEP_STAMP.exists())


if __name__ == "__main__":
    unittest.main()
