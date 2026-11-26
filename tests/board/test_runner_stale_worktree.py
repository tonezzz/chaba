"""Stale dispatch-worktree GC at lane start — card
opencode-retry-stale-worktree (OPS-1039).

A held/failed opencode or kk_mac run leaves dispatch-wt-<tid> behind;
the tid is stable across retries (runner-* unit names truncate the
epoch for long card ids), so every retry used to die on
"worktree already exists" until a human removed the dir. The gate in
runner-agent now reaps the tree when the previous attempt is
provably over (taskdir exit_code/verdict.json, or a dead
lane-family run) and defers while a devin-task-<tid> unit is live
or the tree can't be attributed.

Real git in tmpdirs (bare origin + runner clone + session worktree);
unit/systemctl surfaces are stubbed — no systemd, no network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))

_spec = importlib.util.spec_from_file_location(
    "runner_agent", REPO / "scripts" / "board" / "runner-agent.py")
ra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ra)

TID = "20990101-000000-test-stale-wt"
UNIT = f"devin-task-{TID}"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True)


def commit(repo: Path, path: str, content: str, msg: str) -> None:
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    git(repo, "add", path)
    r = git(repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", msg)
    assert r.returncode == 0, r.stderr


class Case(unittest.TestCase):
    """origin(bare) + runner clone + taskdir under a fake HOME per
    test; the stale worktree is a real registered git worktree."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._env = {k: os.environ.get(k) for k in ("HOME",)}
        self.home = self.tmp / "home"
        self.home.mkdir(parents=True)
        os.environ["HOME"] = str(self.home)

        self.origin = self.tmp / "origin.git"
        self.origin.mkdir()
        r = subprocess.run(["git", "init", "-q", "--bare", "-b",
                            "master", str(self.origin)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        seed = self.tmp / "seed"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(seed)], capture_output=True)
        commit(seed, "file.txt", "base\n", "base")
        r = git(seed, "push", "-q", "-u", "origin", "master")
        assert r.returncode == 0, r.stderr
        self.repo = self.tmp / "runner-repo"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(self.repo)], capture_output=True)

        self.wt = self.home / f"CascadeProjects/dispatch-wt-{TID}"
        self.taskdir = (self.home / ".local/share/devin-dispatch/tasks"
                        / TID)
        self.taskdir.mkdir(parents=True)

        self._mod = {k: getattr(ra, k) for k in ("OPENCODE_LANES",)}
        self._fn = {k: getattr(ra, k) for k in
                    ("sh", "unit_active", "task_runtime", "rt_launch",
                     "opencode_bin", "opencode_needs_standalone",
                     "oc_profiles_module", "dr_module")}
        self.active_units: set = set()
        self.list_units_out = ""
        ra.unit_active = lambda u: u in self.active_units
        ra.task_runtime = lambda: "systemd"
        real_run = subprocess.run

        def fake_sh(cmd, timeout=60, **kw):
            if cmd and cmd[0] == "git":
                return real_run(cmd, capture_output=True, text=True,
                                timeout=timeout)
            if list(cmd[:2]) == ["systemctl", "--user"] and \
                    "list-units" in cmd:
                return types.SimpleNamespace(
                    returncode=0, stdout=self.list_units_out,
                    stderr="")
            return types.SimpleNamespace(returncode=0, stdout="",
                                         stderr="")

        ra.sh = fake_sh
        self.launched: list = []
        ra.rt_launch = lambda unit, desc, shell, **kw: (
            self.launched.append(unit) or "")
        signal.alarm(10)  # hard per-test timeout

    def tearDown(self) -> None:
        signal.alarm(0)
        for k, v in self._mod.items():
            setattr(ra, k, v)
        for k, v in self._fn.items():
            setattr(ra, k, v)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    # ------------------------------------------------------- helpers
    def make_stale_worktree(self, dirty: bool = False) -> None:
        r = git(self.repo, "worktree", "add", "-q", str(self.wt),
                "-b", f"dispatch/{TID}", "origin/master")
        assert r.returncode == 0, r.stderr
        if dirty:
            (self.wt / "scratch.txt").write_text("x\n")

    def gate(self) -> str:
        return ra._stale_worktree_gate(self.repo, self.wt,
                                       self.taskdir, TID)

    # --------------------------------------------------------- tests
    def test_gate_absent_worktree_proceeds(self):
        self.assertEqual(self.gate(), "")

    def test_gate_reaps_finished_run_exit_code(self):
        """The OPS-1021/1039 case: held run -> exit_code durable in
        the taskdir -> the leftover tree is reaped, not fatal."""
        self.make_stale_worktree(dirty=True)
        (self.taskdir / "exit_code").write_text("1\n")
        (self.taskdir / "meta.json").write_text(json.dumps(
            {"executor": "opencode:ops-readonly"}))
        self.assertEqual(self.gate(), "")
        self.assertFalse(self.wt.exists())

    def test_gate_reaps_verdict_only(self):
        self.make_stale_worktree()
        (self.taskdir / "verdict.json").write_text(
            '{"verdict": "fail"}')
        self.assertEqual(self.gate(), "")
        self.assertFalse(self.wt.exists())

    def test_gate_reaps_dead_lane_run_without_exit_code(self):
        """SIGKILL/RuntimeMaxSec/failed-launch residue: lane-family
        meta + no live unit -> reapable even with no exit_code."""
        self.make_stale_worktree()
        (self.taskdir / "meta.json").write_text(json.dumps(
            {"executor": "opencode:profile-run"}))
        self.assertEqual(self.gate(), "")
        self.assertFalse(self.wt.exists())

    def test_gate_defers_active_unit(self):
        """A live devin-task-<tid> unit defers even when a stale
        exit_code from a prior attempt is present — order matters."""
        self.make_stale_worktree()
        (self.taskdir / "exit_code").write_text("0\n")
        self.active_units.add(UNIT)
        err = self.gate()
        self.assertIn("still active", err)
        self.assertTrue(self.wt.is_dir())

    def test_gate_defers_active_followup_unit(self):
        """-fuN followups share the taskdir/worktree — a live one
        defers the reap just like the base unit."""
        self.make_stale_worktree()
        fu = f"{UNIT}-fu1"
        self.active_units.add(fu)
        self.list_units_out = (
            f"{fu}.service loaded active running runner x\n")
        err = self.gate()
        self.assertIn("still active", err)
        self.assertTrue(self.wt.is_dir())

    def test_gate_defers_unattributed_residue(self):
        """Worktree + taskdir with no meta and no usable finish evidence —
        can't prove it's ours or dead -> defer, keep the tree."""
        self.make_stale_worktree()
        err = self.gate()
        self.assertIn("no usable finish evidence", err)
        self.assertTrue(self.wt.is_dir())

    def test_gate_defers_foreign_executor_meta(self):
        self.make_stale_worktree()
        (self.taskdir / "exit_code").write_text("0\n")
        (self.taskdir / "meta.json").write_text(json.dumps(
            {"executor": "devin"}))
        err = self.gate()
        self.assertIn("no usable finish evidence", err)
        self.assertTrue(self.wt.is_dir())

    def test_gate_keeps_locked_worktree(self):
        """git still registers a locked tree -> removal fails ->
        defer rather than rmtree over someone's lock."""
        self.make_stale_worktree()
        (self.taskdir / "exit_code").write_text("0\n")
        r = git(self.repo, "worktree", "lock", str(self.wt))
        assert r.returncode == 0, r.stderr
        err = self.gate()
        self.assertIn("removal failed", err)
        self.assertTrue(self.wt.is_dir())

    def test_gate_rmtrees_unregistered_residue(self):
        """Plain directory residue (never registered / already
        pruned) -> rmtree'd so the path is free."""
        self.wt.mkdir(parents=True)
        (self.wt / "leftover.txt").write_text("x\n")
        (self.taskdir / "exit_code").write_text("0\n")
        self.assertEqual(self.gate(), "")
        self.assertFalse(self.wt.exists())

    # ------------------------------------------- lane integration
    def _opencode_stubs(self) -> None:
        ra.OPENCODE_LANES = True
        ra.opencode_bin = lambda: "/bin/true"
        ra.opencode_needs_standalone = lambda b: False
        ra.oc_profiles_module = lambda: types.SimpleNamespace(
            load_profile=lambda pid: {"id": pid,
                                      "model": {"default": "m"}},
            render_config=lambda synth, prof: {},
            agent_name=lambda pid: "test-agent",
            _fixture_dir=lambda prof: self.tmp / "no-fixture")

        repo_path = str(self.repo)

        class FakeDr:
            def repos(self):
                return {"chaba": {"path": repo_path,
                                  "default_branch": "master"}}

        ra.dr_module = lambda: FakeDr()

    def _card(self) -> dict:
        return {"id": "c1", "title": "t", "spec": "s",
                "action": {"type": "dispatch", "repo": "chaba",
                           "agent_profile": "ops-readonly",
                           "model": "litellm/test-model"}}

    def test_start_opencode_lane_recycles_stale_worktree(self):
        """End-to-end: a finished previous attempt's worktree is
        reaped and the lane proceeds to launch a fresh unit."""
        self._opencode_stubs()
        tid = "c1-12345"
        wt = self.home / f"CascadeProjects/dispatch-wt-{tid}"
        td = (self.home / ".local/share/devin-dispatch/tasks" / tid)
        td.mkdir(parents=True)
        r = git(self.repo, "worktree", "add", "-q", str(wt),
                "-b", f"dispatch/{tid}", "origin/master")
        assert r.returncode == 0, r.stderr
        (td / "exit_code").write_text("1\n")
        (td / "meta.json").write_text(json.dumps(
            {"executor": "opencode:ops-readonly"}))

        unit, out_tid, err = ra._start_opencode_lane(
            self._card(), "free_lane", f"runner-{tid}")
        self.assertEqual(err, "")
        self.assertEqual(unit, f"devin-task-{tid}")
        self.assertEqual(out_tid, tid)
        self.assertEqual(self.launched, [f"devin-task-{tid}"])
        self.assertTrue(wt.is_dir())  # fresh tree, not the stale one
        meta = json.loads((td / "meta.json").read_text())
        self.assertEqual(meta["executor"], "opencode:free_lane")

    def test_start_opencode_lane_defers_on_active_unit(self):
        """A live previous unit -> start defers, tree untouched, no
        launch."""
        self._opencode_stubs()
        tid = "c1-12345"
        wt = self.home / f"CascadeProjects/dispatch-wt-{tid}"
        td = (self.home / ".local/share/devin-dispatch/tasks" / tid)
        td.mkdir(parents=True)
        r = git(self.repo, "worktree", "add", "-q", str(wt),
                "-b", f"dispatch/{tid}", "origin/master")
        assert r.returncode == 0, r.stderr
        (wt / "marker.txt").write_text("live\n")
        (td / "exit_code").write_text("0\n")
        self.active_units.add(f"devin-task-{tid}")

        unit, out_tid, err = ra._start_opencode_lane(
            self._card(), "free_lane", f"runner-{tid}")
        self.assertEqual(unit, "")
        self.assertIn("still active", err)
        self.assertEqual(self.launched, [])
        self.assertTrue((wt / "marker.txt").is_file())


if __name__ == "__main__":
    unittest.main()
