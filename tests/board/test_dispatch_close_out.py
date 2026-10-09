"""End-to-end tests for the dispatch close-out merge step
(scripts/board/dispatch_repos.py — card dispatch-auto-merge).

Builds a bare origin + main clone + dispatch session worktree in a tmpdir
and exercises: checkpoint commit of leftovers, always-push, the
expected_goals gate, --no-ff merge, safe-pull conflict policy (generated
paths auto-resolve, real conflicts report), and the silent no-op path.

No network, no systemd — all git ops stay inside the tmpdir.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
import dispatch_repos as dr  # noqa: E402

TID = "20990101-000000-test-close-out"


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
    """One fixture per test: origin(bare) + main(clone) + session wt."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._old_dir = os.environ.get("DISPATCH_DIR")
        os.environ["DISPATCH_DIR"] = str(self.tmp / "dispatch")

        self.origin = self.tmp / "origin.git"
        self.origin.mkdir()
        r = subprocess.run(["git", "init", "-q", "--bare",
                            "-b", "master", str(self.origin)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        seed = self.tmp / "seed"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(seed)], capture_output=True)
        commit(seed, "file.txt", "base\n", "base")
        commit(seed, "docs/ssot/gen.yml", "v: 0\n", "gen0")
        # a tests/ dir so the merged tree engages the test gate
        commit(seed, "tests/test_smoke.py",
               "def test_ok():\n    assert True\n", "tests")
        r = git(seed, "push", "-q", "-u", "origin", "master")
        assert r.returncode == 0, r.stderr

        self.main = self.tmp / "main"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(self.main)], capture_output=True)
        # the dispatch session worktree + branch
        self.wt = self.tmp / f"dispatch-wt-{TID}"
        r = git(self.main, "worktree", "add", "-q", str(self.wt),
                "-b", f"dispatch/{TID}", "origin/master")
        assert r.returncode == 0, r.stderr
        task = self.tmp / "dispatch" / "tasks" / TID
        task.mkdir(parents=True)
        (task / "meta.json").write_text(json.dumps(
            {"repo": "chaba", "worktree": str(self.wt),
             "branch": f"dispatch/{TID}",
             "unit": f"devin-task-{TID}"}))
        self.card = {"id": "test-card",
                     "action": {"type": "dispatch", "task_id": TID,
                                "repo": "chaba"}}

    def tearDown(self) -> None:
        if self._old_dir is None:
            os.environ.pop("DISPATCH_DIR", None)
        else:
            os.environ["DISPATCH_DIR"] = self._old_dir
        self._td.cleanup()

    def remote_has(self, ref: str, path: str) -> bool:
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             f"{ref}:{path}"], capture_output=True, text=True)
        return r.returncode == 0

    def test_happy_path_merges_and_checkpoints(self):
        commit(self.wt, "feature.py", "print('hi')\n", "work")
        (self.wt / "dispatch-outcome-2099.md").write_text("outcome\n")
        (self.wt / "docs/ssot/jobs/kanban/x.yml").parent.mkdir(
            parents=True, exist_ok=True)
        (self.wt / "docs/ssot/jobs/kanban/x.yml").write_text("job: 1\n")

        res = dr.close_out(self.card)

        self.assertTrue(res["merged"], res)
        self.assertFalse(res.get("noop"))
        cp = res["checkpoint"]
        self.assertTrue(cp["committed"], cp)
        self.assertEqual(cp["files"], 2)          # two leftovers
        self.assertEqual(dr.dirty_count(self.wt), 0)
        self.assertTrue(res.get("pushed"), res)
        # branch really on origin
        r = git(self.main, "ls-remote", "--heads", "origin",
                f"dispatch/{TID}")
        self.assertIn(f"dispatch/{TID}", r.stdout)
        # merge commit landed with --no-ff (two parents) on origin/master
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "cat-file", "-p",
             "master"], capture_output=True, text=True)
        self.assertGreaterEqual(r.stdout.count("\nparent "), 2, r.stdout)
        self.assertTrue(self.remote_has("master", "feature.py"))
        self.assertTrue(
            self.remote_has("master", "dispatch-outcome-2099.md"))
        notes = dr.close_out_notes(res)
        self.assertTrue(any("auto-merged" in n for n in notes), notes)
        self.assertTrue(any("checkpoint" in n for n in notes), notes)

    def test_noop_run_skips_silently(self):
        # branch exists but produced nothing — head == base tip is NOT
        # merged work (a 'merged' stamp would false-positive verified)
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"])
        self.assertTrue(res["noop"])
        self.assertEqual(dr.close_out_notes(res),
                         [n for n in dr.close_out_notes(res)
                          if "pushed" in n or "checkpoint" in n])

    def test_real_conflict_reports_paths(self):
        commit(self.wt, "file.txt", "session\n", "session change")
        commit(self.main, "file.txt", "upstream\n", "upstream change")
        r = git(self.main, "push", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr

        res = dr.close_out(self.card)

        self.assertFalse(res["merged"], res)
        self.assertEqual(res["conflicts"], ["file.txt"], res)
        self.assertIn("upstream", subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             "master:file.txt"], capture_output=True, text=True).stdout)
        notes = dr.close_out_notes(res)
        self.assertTrue(any("conflict" in n and "file.txt" in n
                            for n in notes), notes)

    def test_generated_conflict_auto_resolves(self):
        commit(self.wt, "docs/ssot/gen.yml", "v: session\n", "gen-s")
        commit(self.main, "docs/ssot/gen.yml", "v: upstream\n", "gen-u")
        r = git(self.main, "push", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr

        res = dr.close_out(self.card)

        self.assertTrue(res["merged"], res)
        out = subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             "master:docs/ssot/gen.yml"], capture_output=True,
            text=True).stdout
        self.assertIn("upstream", out)  # safe-pull: upstream wins

    def test_goals_gate_holds_merge(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self.card["expected_goals"] = [
            {"id": "nope", "check": "command false"},
            {"id": "yes", "check": "command true"}]
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"])
        self.assertTrue(res["gate"]["ran"])
        self.assertEqual(res["gate"]["bad"], ["nope"])
        notes = dr.close_out_notes(res)
        self.assertTrue(any("expected_goals" in n for n in notes), notes)
        # the branch still pushed — work is not stranded
        r = git(self.main, "ls-remote", "--heads", "origin",
                f"dispatch/{TID}")
        self.assertIn(f"dispatch/{TID}", r.stdout)

    def test_goals_gate_pass_merges(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self.card["expected_goals"] = [
            {"id": "built", "check": "file-exists feature.py"}]
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)

    def test_malformed_goals_block(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self.card["expected_goals"] = [
            {"id": "prose", "check": "make it work"}]
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"])
        self.assertFalse(res["gate"]["ok"])

    def test_missing_session_is_silent_noop(self):
        card = {"id": "nope",
                "action": {"type": "dispatch", "task_id": "gone",
                           "repo": "chaba"}}
        res = dr.close_out(card)
        self.assertFalse(res["merged"])
        self.assertTrue(res.get("skipped"))

    # ------------------------------------------------------ test gate
    # The merged tree always has tests/ (seeded above); REPO_TESTS["chaba"]
    # is pointed at fake commands so the suite doesn't depend on a real
    # pytest install.

    def _with_test_gate(self, cfg: dict) -> None:
        old = dr.REPO_TESTS.get("chaba")
        dr.REPO_TESTS["chaba"] = cfg

        def restore():
            if old is None:
                dr.REPO_TESTS.pop("chaba", None)
            else:
                dr.REPO_TESTS["chaba"] = old
        self.addCleanup(restore)

    def test_gate_red_suite_holds_merge(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self._with_test_gate({
            "command": "echo 'FAILED tests/test_x.py::test_broke - assert "
                       "False' >&2; exit 1",
            "timeout": 30})
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"], res)
        self.assertTrue(res["tests"]["ran"])
        self.assertFalse(res["tests"]["ok"])
        self.assertEqual(res["test_failures"],
                         ["tests/test_x.py::test_broke"])
        # the merged tree must NOT be on origin — but the branch pushed,
        # so the work isn't stranded for the retry
        self.assertFalse(self.remote_has("master", "feature.py"))
        r = git(self.main, "ls-remote", "--heads", "origin",
                f"dispatch/{TID}")
        self.assertIn(f"dispatch/{TID}", r.stdout)
        notes = dr.close_out_notes(res)
        self.assertTrue(any("test gate" in n and "test_broke" in n
                            for n in notes), notes)

    def test_gate_green_merges_and_notes(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self._with_test_gate({"command": "exit 0", "timeout": 30})
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)
        self.assertTrue(res["tests"]["ok"])
        self.assertTrue(self.remote_has("master", "feature.py"))
        self.assertTrue(any("test gate passed" in n
                            for n in dr.close_out_notes(res)))

    def test_gate_off_switch_merges(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        os.environ["KANBAN_TESTGATE"] = "0"
        self.addCleanup(os.environ.pop, "KANBAN_TESTGATE")
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)
        self.assertFalse(res["tests"]["ran"])
        self.assertEqual(res["tests"]["skipped"], "KANBAN_TESTGATE=0")

    def test_gate_timeout_holds_merge(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self._with_test_gate({"command": "sleep 5", "timeout": 1})
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"], res)
        self.assertTrue(any("timeout" in f
                            for f in res.get("test_failures") or []),
                        res)
        self.assertIn("timed out", res["tests"]["error"])

    def test_gate_missing_runner_fails_open(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        self._with_test_gate(
            {"command": "no-such-pytest-bin-ci-test-gate", "timeout": 10})
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"], res)
        self.assertIn("fail-open", res["tests"]["skipped"])

    def test_gate_no_tests_dir_skips(self):
        bare = self.tmp / "no-tests"
        bare.mkdir()
        r = dr.run_test_gate(bare, "chaba")
        self.assertTrue(r["ok"])
        self.assertFalse(r["ran"])
        self.assertIn("no tests", r["skipped"])

    @unittest.skipUnless(
        subprocess.run(["python3", "-c", "import pytest"],
                       capture_output=True).returncode == 0,
        "pytest not installed")
    def test_gate_real_pytest_names_failure(self):
        commit(self.wt, "tests/test_gate_target.py",
               "def test_broke():\n    assert False\n", "red test")
        res = dr.close_out(self.card)
        self.assertFalse(res["merged"], res)
        self.assertTrue(res.get("test_failures"), res)
        self.assertTrue(any("test_broke" in f
                            for f in res["test_failures"]),
                        res["test_failures"])


class MergeRetryTest(unittest.TestCase):
    """kanban-dispatch merge_pending_one: a close_out test-gate failure
    rides the same rails as conflicts — verified=False plus an informed
    auto-retry requeue (action.last_failure carries the test names)."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "kanban_dispatch",
            REPO / "scripts" / "board" / "kanban-dispatch.py")
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_testgate_failure_requeues_with_last_failure(self):
        mod = self.mod
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "gate-card.yml"
        path.write_text(
            "id: gate-card\ncolumn: review\n"
            "action: {type: dispatch, status: done, task_id: t-gate}\n")
        res = {"merged": False,
               "tests": {"ran": True, "ok": False,
                         "command": "pytest tests",
                         "failed": ["tests/test_x.py::test_broke"]},
               "test_failures": ["tests/test_x.py::test_broke"]}
        with mock.patch.object(dr, "close_out", return_value=res), \
                mock.patch.object(mod, "ops_event"), \
                mock.patch.object(mod, "session_end_notes",
                                  return_value=[]):
            out = mod.merge_pending_one(path)
        self.assertIn("merge", out)
        card = yaml.safe_load(path.read_text())
        a = card["action"]
        self.assertEqual(a["status"], "queued")
        self.assertIs(a["verified"], False)
        self.assertEqual(a["attempts"], 1)
        self.assertIn("test_broke", a["last_failure"])

    def test_clean_merge_stamps_verified(self):
        mod = self.mod
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "ok-card.yml"
        path.write_text(
            "id: ok-card\ncolumn: review\n"
            "action: {type: dispatch, status: done, task_id: t-ok}\n")
        res = {"merged": True, "noop": True,
               "note": "dispatch/t-ok already in origin/master"}
        with mock.patch.object(dr, "close_out", return_value=res), \
                mock.patch.object(mod, "session_end_notes",
                                  return_value=[]):
            out = mod.merge_pending_one(path)
        self.assertEqual(out, "noop")
        card = yaml.safe_load(path.read_text())
        self.assertIs(card["action"]["verified"], True)


if __name__ == "__main__":
    unittest.main()
