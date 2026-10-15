"""Worktree GC at card close — card dispatch-worktree-gc.

Covers dispatch_repos.gc_worktree / gc_session (runner-agent +
kanban-dispatch close path) and merge-sweep's REMOTE_GC_PROBE /
gc_runner_worktree (the salvage path — dell merged the head it fetched,
the runner's tree is then cleaned over ssh; the probe is exercised here
through the same python3-stdin transport it ships over).

Guards under test: clean+merged -> worktree + dispatch branch removed;
dirty -> preserved; unmerged -> preserved; locked -> preserved; active
unit naming and KANBAN_WTGC=0 -> disabled. No network, no systemd —
all git ops stay inside the tmpdir.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
import dispatch_repos as dr  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "merge_sweep", REPO / "scripts" / "board" / "merge-sweep.py")
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)

_spec2 = importlib.util.spec_from_file_location(
    "runner_agent", REPO / "scripts" / "board" / "runner-agent.py")
ra = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(ra)

TID = "20990101-000000-test-wtgc"
BRANCH = f"dispatch/{TID}"


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
    """origin(bare) + runner clone + session worktree per test."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._env = {k: os.environ.get(k)
                     for k in ("DISPATCH_DIR", "KANBAN_WTGC",
                               "BOARD_API")}
        os.environ["DISPATCH_DIR"] = str(self.tmp / "dispatch")
        os.environ["BOARD_API"] = "http://127.0.0.1:9"

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
        self.wt = self.tmp / f"dispatch-wt-{TID}"
        r = git(self.repo, "worktree", "add", "-q", str(self.wt),
                "-b", BRANCH, "origin/master")
        assert r.returncode == 0, r.stderr

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    # ------------------------------------------------------- helpers
    def land_on_origin(self) -> str:
        """Commit work in the session worktree, merge --no-ff into
        origin/master via a third clone, refetch in the runner repo.
        Returns the worktree HEAD sha."""
        commit(self.wt, "work.py", "x=1\n", "session work")
        head = git(self.wt, "rev-parse", "HEAD").stdout.strip()
        r = git(self.wt, "push", "-q", "origin", BRANCH)
        assert r.returncode == 0, r.stderr
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(other)], capture_output=True)
        git(other, "config", "user.name", "t")
        git(other, "config", "user.email", "t@t")
        r = git(other, "fetch", "-q", "origin", BRANCH)
        assert r.returncode == 0, r.stderr
        r = git(other, "merge", "--no-ff", "--no-edit", "FETCH_HEAD")
        assert r.returncode == 0, r.stderr
        r = git(other, "push", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr
        r = git(self.repo, "fetch", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr
        return head

    def remote_has(self, ref: str, path: str) -> bool:
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             f"{ref}:{path}"], capture_output=True, text=True)
        return r.returncode == 0

    def probe_gc(self, head: str) -> dict:
        """REMOTE_GC_PROBE through the same transport merge-sweep uses
        for a local runner (python3 reads the script from stdin)."""
        r = ms._py(ms.REMOTE_GC_PROBE, str(self.wt), BRANCH, head, TID)
        assert isinstance(r, dict), r
        return r

    # --------------------------------------------------------- tests
    def test_clean_merged_removes_worktree_and_branch(self):
        head = self.land_on_origin()
        r = dr.gc_worktree(self.wt, "origin/master", BRANCH, TID)
        self.assertIn(f"worktree {self.wt}", r.get("removed") or [])
        self.assertIn(f"branch {BRANCH}", r.get("removed") or [])
        self.assertFalse(self.wt.is_dir())
        gone = git(self.repo, "rev-parse", "--verify", "--quiet",
                   f"refs/heads/{BRANCH}")
        self.assertNotEqual(gone.returncode, 0)
        self.assertNotIn(BRANCH, (git(
            self.repo, "worktree", "list", "--porcelain").stdout))

    def test_dirty_worktree_preserved(self):
        self.land_on_origin()
        (self.wt / "leftover.md").write_text("uncommitted\n")
        r = dr.gc_worktree(self.wt, "origin/master", BRANCH, TID)
        self.assertEqual(r.get("removed"), [])
        self.assertIn("dirty", r.get("skipped") or "")
        self.assertTrue(self.wt.is_dir())
        self.assertTrue(git(self.repo, "rev-parse", "--verify",
                            "--quiet", BRANCH).returncode == 0)

    def test_unmerged_branch_preserved(self):
        commit(self.wt, "wip.py", "x=1\n", "never pushed/merged")
        r = dr.gc_worktree(self.wt, "origin/master", BRANCH, TID)
        self.assertEqual(r.get("removed"), [])
        self.assertIn("unmerged", r.get("skipped") or "")
        self.assertTrue(self.wt.is_dir())
        self.assertTrue(git(self.repo, "rev-parse", "--verify",
                            "--quiet", BRANCH).returncode == 0)

    def test_locked_worktree_preserved(self):
        self.land_on_origin()
        r = git(self.repo, "worktree", "lock", str(self.wt))
        assert r.returncode == 0, r.stderr
        r = dr.gc_worktree(self.wt, "origin/master", BRANCH, TID)
        self.assertEqual(r.get("removed"), [])
        self.assertTrue(r.get("error"))
        self.assertTrue(self.wt.is_dir())

    def test_kill_switch(self):
        self.land_on_origin()
        os.environ["KANBAN_WTGC"] = "0"
        r = dr.gc_worktree(self.wt, "origin/master", BRANCH, TID)
        self.assertEqual(r.get("removed"), [])
        self.assertTrue(self.wt.is_dir())

    def test_gc_session_notes(self):
        """The close_out-result wrapper emits the one-line comms note
        listing what was removed (runner-agent / kanban-dispatch path)."""
        head = self.land_on_origin()
        res = {"merged": True,
               "session": {"worktree": self.wt, "head": head,
                           "base_ref": "origin/master", "branch": BRANCH,
                           "task_id": TID}}
        notes = dr.gc_session(res)
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("worktree GC: removed", notes[0])
        self.assertIn(f"worktree {self.wt}", notes[0])
        self.assertIn(f"branch {BRANCH}", notes[0])
        self.assertFalse(self.wt.is_dir())

    def test_gc_session_keeps_dirty(self):
        head = self.land_on_origin()
        (self.wt / "dirty.txt").write_text("x\n")
        res = {"merged": True,
               "session": {"worktree": self.wt, "head": head,
                           "base_ref": "origin/master", "branch": BRANCH,
                           "task_id": TID}}
        notes = dr.gc_session(res)
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("worktree kept", notes[0])
        self.assertTrue(self.wt.is_dir())

    def test_gc_session_unmerged_silent_or_kept(self):
        """Merged=False result (conflict path): the head isn't inside
        base — worktree is kept."""
        commit(self.wt, "wip.py", "x=1\n", "unmerged")
        head = git(self.wt, "rev-parse", "HEAD").stdout.strip()
        res = {"merged": False, "conflicts": ["file.txt"],
               "session": {"worktree": self.wt, "head": head,
                           "base_ref": "origin/master", "branch": BRANCH,
                           "task_id": TID}}
        dr.gc_session(res)
        self.assertTrue(self.wt.is_dir())

    def test_empty_session_gc(self):
        """noop session (head == base tip) — nothing to lose, the
        worktree still goes (disk hygiene is the point of the card)."""
        head = git(self.wt, "rev-parse", "HEAD").stdout.strip()
        res = {"noop": True, "skipped": "session produced no commits",
               "session": {"worktree": self.wt, "head": head,
                           "base_ref": "origin/master", "branch": BRANCH,
                           "task_id": TID}}
        notes = dr.gc_session(res)
        self.assertEqual(len(notes), 1, notes)
        self.assertFalse(self.wt.is_dir())

    # -------------------------------------------------- remote probe
    def test_remote_probe_removes_merged(self):
        head = self.land_on_origin()
        r = self.probe_gc(head)
        self.assertIn(f"worktree {self.wt}", r.get("removed") or [])
        self.assertIn(f"branch {BRANCH}", r.get("removed") or [])
        self.assertFalse(self.wt.is_dir())

    def test_remote_probe_keeps_dirty(self):
        head = self.land_on_origin()
        (self.wt / "scratch").mkdir()
        (self.wt / "scratch" / "f").write_text("x\n")
        r = self.probe_gc(head)
        self.assertEqual(r.get("removed"), [])
        self.assertIn("dirty", r.get("skipped") or "")
        self.assertTrue(self.wt.is_dir())

    def test_remote_probe_keeps_unmerged(self):
        # a sha NOT containing the wt head (base tip) — the probe must
        # refuse to remove a tree with commits beyond the merged sha
        head = git(self.repo, "rev-parse", "origin/master"
                   ).stdout.strip()
        commit(self.wt, "wip.py", "x=1\n", "ahead of merge")
        r = self.probe_gc(head)
        self.assertEqual(r.get("removed"), [])
        self.assertIn("merged head", r.get("skipped") or "")
        self.assertTrue(self.wt.is_dir())

    def test_remote_probe_gone_worktree(self):
        head = git(self.repo, "rev-parse", "origin/master"
                   ).stdout.strip()
        r = git(self.repo, "worktree", "remove", str(self.wt))
        assert r.returncode == 0, r.stderr
        r = self.probe_gc(head)
        self.assertEqual(r.get("removed"), [])
        self.assertIn("gone", r.get("skipped") or "")

    # -------------------------------------------- gc_runner_worktree
    def test_sweep_gc_posts_comms_note(self):
        """gc_runner_worktree: the one-line comms note lands on the card
        (board-api unreachable -> locked-YAML fallback path)."""
        head = self.land_on_origin()
        cards = self.tmp / "cards"
        cards.mkdir()
        cid = "test-gc-card"
        (cards / f"{cid}.yml").write_text(yaml.safe_dump(
            {"id": cid, "column": "review", "comms": []},
            sort_keys=False))
        old_dir, old_render = ms.CARD_DIR, ms.RENDER
        ms.CARD_DIR = cards
        ms.RENDER = Path("/nonexistent-render")
        try:
            card = {"id": cid}
            probe = {"worktree": str(self.wt), "wt_exists": True,
                     "branch": BRANCH}
            ok = ms.gc_runner_worktree(card, "", probe, head, TID,
                                       dry=False)
        finally:
            ms.CARD_DIR, ms.RENDER = old_dir, old_render
        self.assertTrue(ok)
        self.assertFalse(self.wt.is_dir())
        c = yaml.safe_load((cards / f"{cid}.yml").read_text())
        gc = [m for m in c.get("comms") or []
              if "merge-sweep GC" in (m.get("text") or "")]
        self.assertTrue(gc, c.get("comms"))
        self.assertIn(f"worktree {self.wt}", gc[0]["text"])
        self.assertIn(BRANCH, gc[0]["text"])

    # --------------------------------- runner-agent close path e2e
    def test_runner_agent_close_out_merges_and_gcs(self):
        """The card-close path end-to-end (no HTTP — close_out_merge
        only needs the session meta + git): the branch merges into
        origin/master and the worktree+branch are removed, with the
        comms line listing them."""
        task = self.tmp / "dispatch" / "tasks" / TID
        task.mkdir(parents=True)
        (task / "meta.json").write_text(json.dumps(
            {"repo": "chaba", "worktree": str(self.wt),
             "branch": BRANCH, "default_branch": "master"}))
        commit(self.wt, "work.py", "x=1\n", "session work")
        card = {"id": "c", "expected_goals": None,
                "action": {"type": "dispatch", "repo": "chaba"}}
        verified, notes = ra.close_out_merge("c", {"tid": TID}, card)
        self.assertIs(verified, True)
        self.assertTrue(self.remote_has("master", "work.py"))
        self.assertFalse(self.wt.is_dir())
        self.assertTrue(any("worktree GC: removed" in n
                            and str(self.wt) in n and BRANCH in n
                            for n in notes), notes)
        gone = git(self.repo, "rev-parse", "--verify", "--quiet",
                   f"refs/heads/{BRANCH}")
        self.assertNotEqual(gone.returncode, 0)

    def test_sweep_gc_keeps_dirty_no_comms(self):
        head = self.land_on_origin()
        (self.wt / "x.tmp").write_text("x\n")
        cards = self.tmp / "cards"
        cards.mkdir()
        cid = "test-gc-card"
        (cards / f"{cid}.yml").write_text(yaml.safe_dump(
            {"id": cid, "column": "review", "comms": []},
            sort_keys=False))
        old_dir = ms.CARD_DIR
        ms.CARD_DIR = cards
        try:
            ok = ms.gc_runner_worktree(
                {"id": cid}, "",
                {"worktree": str(self.wt), "wt_exists": True,
                 "branch": BRANCH}, head, TID, dry=False)
        finally:
            ms.CARD_DIR = old_dir
        self.assertFalse(ok)
        self.assertTrue(self.wt.is_dir())
        c = yaml.safe_load((cards / f"{cid}.yml").read_text())
        self.assertFalse(c.get("comms"))


if __name__ == "__main__":
    unittest.main()
