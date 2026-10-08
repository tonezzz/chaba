"""End-to-end tests for merge-sweep (scripts/board/merge-sweep.py —
card dispatch-merge-sweep).

Builds a bare origin + a 'served' clone + a separate 'runner' clone with
a dispatch session worktree in a tmpdir — the stranded-branch case: the
runner finished work but never reached origin, so the sweep fetches the
head over the runner's path and merges into the served checkout.

Covers: clean merge lands + verified stamp, strict stop-and-report
conflicts (no side taken), dirty worktree flag, failed-run flag,
in-flight skip, stale-running rescue, comms task_id resolution, and the
zombie flag. No network, no systemd — all git ops stay in the tmpdir;
the 'remote runner' is exercised through the local code path (identical
git semantics, ssh is only the transport).
"""

from __future__ import annotations

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
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "merge_sweep", REPO / "scripts" / "board" / "merge-sweep.py")
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)

TID = "20990101-000000-test-sweep"


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
    """One fixture per test: origin(bare) + served(clone, the merge
    target) + runner(clone) + session worktree + card dir."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._env = {}
        for k in ("DISPATCH_DIR", "CHABA_REPO", "MERGE_SWEEP_TARGETS",
                  "BOARD_API", "ZOMBIE_AGE_H", "ZOMBIE_IDLE_MIN"):
            self._env[k] = os.environ.get(k)
        os.environ["DISPATCH_DIR"] = str(self.tmp / "dispatch")
        os.environ["BOARD_API"] = "http://127.0.0.1:9"  # refuse fast

        # bare origin with a base commit
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

        # the served checkout (merge target) and the runner's clone
        self.served = self.tmp / "served"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(self.served)], capture_output=True)
        self.runner_repo = self.tmp / "runner-repo"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(self.runner_repo)], capture_output=True)

        # session worktree on the 'runner' (linked wt of runner-repo)
        self.wt = self.tmp / f"dispatch-wt-{TID}"
        r = git(self.runner_repo, "worktree", "add", "-q",
                str(self.wt), "-b", f"dispatch/{TID}", "origin/master")
        assert r.returncode == 0, r.stderr

        # task registry on the 'runner' (local probe reads DISPATCH_DIR)
        task = self.tmp / "dispatch" / "tasks" / TID
        task.mkdir(parents=True)
        (task / "meta.json").write_text(json.dumps(
            {"repo": "chaba", "worktree": str(self.wt),
             "branch": f"dispatch/{TID}",
             "default_branch": "master",
             "unit": f"devin-task-{TID}"}))

        # cards dir + merge target map (module-level constants patched)
        self.cards = self.tmp / "cards-repo/docs/ssot/kanban/cards"
        self.cards.mkdir(parents=True)
        self._mod = {
            "CARD_DIR": ms.CARD_DIR, "SERVED": dict(ms.SERVED),
            "API": ms.API, "RENDER": ms.RENDER,
            "ZOMBIE_AGE_S": ms.ZOMBIE_AGE_S,
            "ZOMBIE_IDLE_S": ms.ZOMBIE_IDLE_S,
        }
        ms.CARD_DIR = self.cards
        ms.SERVED = {"chaba": str(self.served)}
        ms.API = "http://127.0.0.1:9"
        ms.RENDER = Path("/nonexistent-render")

    def tearDown(self) -> None:
        for k, v in self._mod.items():
            setattr(ms, k, v)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    # ------------------------------------------------------- helpers
    def write_card(self, cid: str = "test-card", **kw) -> dict:
        card = {"id": cid, "column": "review",
                "action": {"type": "dispatch", "status": "done",
                           "task_id": TID, "repo": "chaba"},
                "comms": []}
        card.update(kw)
        (self.cards / f"{cid}.yml").write_text(
            yaml.safe_dump(card, allow_unicode=True, sort_keys=False))
        return card

    def read_card(self, cid: str = "test-card") -> dict:
        return yaml.safe_load((self.cards / f"{cid}.yml").read_text())

    def remote_has(self, ref: str, path: str) -> bool:
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             f"{ref}:{path}"], capture_output=True, text=True)
        return r.returncode == 0

    def remote_master_parents(self) -> int:
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "cat-file", "-p",
             "master"], capture_output=True, text=True)
        return r.stdout.count("\nparent ")

    # --------------------------------------------------------- tests
    def test_stranded_branch_merges_and_verifies(self):
        commit(self.wt, "feature.py", "print('hi')\n", "work")
        card = self.write_card()
        changed = ms.sweep_card(card, {}, dry=False)
        self.assertTrue(changed)
        self.assertTrue(self.remote_has("master", "feature.py"))
        self.assertGreaterEqual(self.remote_master_parents(), 2)  # --no-ff
        c = self.read_card()
        self.assertIs(c["action"].get("verified"), True)
        self.assertTrue(any("merge-sweep" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])

    def test_clean_noop_when_nothing_produced(self):
        before = subprocess.run(
            ["git", "--git-dir", str(self.origin), "rev-parse",
             "master"], capture_output=True, text=True).stdout.strip()
        card = self.write_card()  # wt head == base — nothing new
        changed = ms.sweep_card(card, {}, dry=False)
        self.assertTrue(changed)  # verified stamp + comms
        c = self.read_card()
        self.assertIs(c["action"].get("verified"), True)
        self.assertTrue(any("already in" in m.get("text", "")
                            for m in c.get("comms") or []), c["comms"])
        after = subprocess.run(
            ["git", "--git-dir", str(self.origin), "rev-parse",
             "master"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(before, after)

    def test_verified_card_skips_early(self):
        commit(self.wt, "x.py", "x=1\n", "work")
        card = self.write_card(
            action={"type": "dispatch", "status": "done",
                    "task_id": TID, "repo": "chaba", "verified": True})
        self.assertFalse(ms.sweep_card(card, {}, dry=False))
        self.assertFalse(self.remote_has("master", "x.py"))

    def test_conflict_posts_request_not_wrong_merge(self):
        commit(self.wt, "file.txt", "session\n", "session change")
        # upstream moves the same path after the branch was cut
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(other)], capture_output=True)
        commit(other, "file.txt", "upstream\n", "upstream change")
        r = git(other, "push", "-q", "origin", "master")
        assert r.returncode == 0, r.stderr

        card = self.write_card()
        changed = ms.sweep_card(card, {}, dry=False)
        self.assertTrue(changed)
        c = self.read_card()
        # master still carries upstream — no side was silently taken
        body = subprocess.run(
            ["git", "--git-dir", str(self.origin), "show",
             "master:file.txt"], capture_output=True, text=True).stdout
        self.assertIn("upstream", body)
        reqs = c.get("requests") or []
        self.assertTrue(any(r.get("id") == "merge-conflict"
                            and "file.txt" in (r.get("ask") or "")
                            for r in reqs), reqs)
        self.assertNotEqual(c["action"].get("verified"), True)
        # a second sweep doesn't raise a duplicate while it stays open
        card2 = self.read_card()
        ms.sweep_card(card2, {}, dry=False)
        c2 = self.read_card()
        self.assertEqual(
            sum(1 for r in c2.get("requests") or []
                if str(r.get("id", "")).startswith("merge-conflict")), 1)

    def test_dirty_worktree_flagged_not_fetched(self):
        commit(self.wt, "feature.py", "x=1\n", "work")
        (self.wt / "leftover.md").write_text("uncommitted\n")
        card = self.write_card()
        self.assertFalse(ms.sweep_card(card, {}, dry=False))
        self.assertFalse(self.remote_has("master", "feature.py"))
        c = self.read_card()
        self.assertTrue(any("dirty" in m.get("text", "")
                            for m in c.get("comms") or []))
        self.assertEqual(
            (c["action"].get("sweep") or {}).get("dirty"), 1)

    def test_failed_run_flagged_not_merged(self):
        commit(self.wt, "partial.py", "x=1\n", "partial")
        card = self.write_card(
            action={"type": "dispatch", "status": "failed",
                    "task_id": TID, "repo": "chaba"})
        self.assertFalse(ms.sweep_card(card, {}, dry=False))
        self.assertFalse(self.remote_has("master", "partial.py"))
        c = self.read_card()
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("failed_noted"))

    def test_running_active_skipped(self):
        commit(self.wt, "live.py", "x=1\n", "wip")
        card = self.write_card(
            column="doing",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba"})
        active = {TID: {"unit": f"devin-task-{TID}", "age_s": 60,
                        "idle_s": 5}}
        self.assertFalse(ms.sweep_card(card, active, dry=False))
        self.assertFalse(self.remote_has("master", "live.py"))

    def test_stale_running_branch_rescued(self):
        commit(self.wt, "done.py", "x=1\n", "finished-but-unreported")
        card = self.write_card(
            column="doing",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba"})
        self.assertTrue(ms.sweep_card(card, {}, dry=False))
        self.assertTrue(self.remote_has("master", "done.py"))
        c = self.read_card()
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("stale_running"))
        self.assertIs(c["action"].get("verified"), True)

    def test_task_id_from_comms(self):
        commit(self.wt, "comms.py", "x=1\n", "work")
        card = {"id": "test-card", "column": "review",
                "action": {"type": "dispatch", "status": "done",
                           "runner": "nowhere"},
                "comms": [{"at": "2026-01-01 00:00", "from": "nowhere",
                           "text": f"started devin-task-{TID} on "
                                   f"nowhere (dispatch)"}]}
        (self.cards / "test-card.yml").write_text(
            yaml.safe_dump(card, allow_unicode=True, sort_keys=False))
        # prove tid resolved from comms and the merge pipeline ran —
        # the 'nowhere' runner can't really fetch, so stub the
        # transport to the local path (same git semantics)
        probed = {}
        orig_probe, orig_fetch = ms.session_probe, ms.fetch_session

        def spy_probe(host, tid):
            probed["tid"] = tid
            return orig_probe("", tid)

        def spy_fetch(repo, host, probe):
            return orig_fetch(repo, "", probe)
        ms.session_probe, ms.fetch_session = spy_probe, spy_fetch
        try:
            ms.sweep_card(card, {}, dry=False)
        finally:
            ms.session_probe, ms.fetch_session = orig_probe, orig_fetch
        self.assertEqual(probed.get("tid"), TID)
        self.assertTrue(self.remote_has("master", "comms.py"))

    def test_zombie_flag_once(self):
        card = self.write_card(
            column="doing",
            action={"type": "dispatch", "status": "running",
                    "task_id": TID, "repo": "chaba"})
        host_units = {"mn01": [{"task": TID,
                                "unit": f"devin-task-{TID}.service",
                                "age_s": 30 * 3600,
                                "idle_s": 3 * 3600}]}
        n = ms.sweep_zombies(host_units, {TID: card}, dry=False)
        self.assertEqual(n, 1)
        c = self.read_card()
        self.assertTrue(any("zombie" in m.get("text", "")
                            for m in c.get("comms") or []))
        # second sweep — already flagged, no repeat
        card2 = self.read_card()
        n2 = ms.sweep_zombies(host_units, {TID: card2}, dry=False)
        self.assertEqual(n2, 0)

    def test_runner_probe_feeds_script_on_stdin(self):
        # regression: `python3 -` reads the program from stdin — an
        # earlier version never passed input= so every probe silently
        # ran an empty program and returned {}
        res = ms.runner_probe("", "import json;print(json.dumps({'ok':1}))")
        self.assertEqual(res, {"ok": 1})
        res = ms.runner_probe("", "import json,sys;"
                                  "print(json.dumps({'a':sys.argv[1]}))",
                              "hello")
        self.assertEqual(res, {"a": "hello"})

    def test_zombie_below_threshold_ignored(self):
        card = self.write_card()
        host_units = {"mn01": [{"task": TID, "unit": "u",
                                "age_s": 7 * 3600,   # old enough…
                                "idle_s": 60}]}       # …but still alive
        n = ms.sweep_zombies(host_units, {TID: card}, dry=False)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
