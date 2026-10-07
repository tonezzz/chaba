"""End-to-end tests for the dispatch close-out merge step
(scripts/board/dispatch_repos.py — card dispatch-auto-merge).

Builds a bare origin + main clone + dispatch session worktree in a tmpdir
and exercises: checkpoint commit of leftovers, always-push, the
expected_goals gate, --no-ff merge, safe-pull conflict policy (generated
paths auto-resolve, real conflicts report), and the silent no-op path.

No network, no systemd — all git ops stay inside the tmpdir.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
        # branch exists but produced nothing — no commits above base
        res = dr.close_out(self.card)
        self.assertTrue(res["merged"])
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


if __name__ == "__main__":
    unittest.main()
