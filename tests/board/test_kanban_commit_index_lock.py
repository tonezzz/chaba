"""Regression tests for kanban-commit's stale .git/index.lock recovery.

Card idc03-writer-hardening-index-lock-race-l-f77129: a git killed
mid-add/commit leaves .git/index.lock behind; every later index write
fails "Unable to create index.lock" and the sweep stalled silently (the
add loop swallows the failure, so live board edits never committed).

The sweep now clears the lock when it is provably stale — a recorded or
fuser-visible holder pid that is dead, or an mtime older than
KANBAN_INDEX_LOCK_STALE_S (default 900s = 15min) — at most once per
tick, and leaves fresh live locks alone.

Note: git itself leaves index.lock EMPTY (verified on git 2.53), so the
"holder pid" path covers pid-token files and fuser-visible openers; the
age check is the primary criterion for real git locks.

Like test_kanban_commit_guard.py this runs the real script against a
minimal scratch repo — safe to gate CI on.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/kanban-commit.sh"
PROSE = "docs/ssot/kanban/ssot.kanban.yml"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("git", *args), cwd=cwd, text=True,
                          capture_output=True, check=True)


def _dead_pid() -> int:
    """A pid that is guaranteed dead: spawn, reap, confirm ESRCH."""
    p = subprocess.Popen(["true"])
    p.wait()
    for _ in range(50):
        try:
            os.kill(p.pid, 0)
        except ProcessLookupError:
            return p.pid
        time.sleep(0.05)
    raise RuntimeError(f"pid {p.pid} still alive after reap")


class KanbanCommitIndexLockTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        origin = root / "origin.git"
        _git(root, "init", "-q", "--bare", "--initial-branch=master", str(origin))

        seed = root / "seed"
        _git(root, "clone", "-q", str(origin), str(seed))
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            _git(seed, "config", k, v)
        (seed / "docs/ssot/kanban/cards").mkdir(parents=True)
        (seed / "docs/ssot/kanban/cards/.gitkeep").touch()
        (seed / PROSE).write_text("title: kanban\n", encoding="utf-8")
        _git(seed, "add", "-A")
        _git(seed, "commit", "-qm", "seed")
        _git(seed, "push", "-q", "origin", "master")

        self.served = root / "served"
        _git(root, "clone", "-q", str(origin), str(self.served))
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            _git(self.served, "config", k, v)

        self.lock = self.served / ".git" / "index.lock"
        self.env = os.environ.copy()
        self.env.update({
            "KANBAN_REPO": str(self.served),
            "CHABA_SERVED_CHECKOUT": str(self.served),
            "CHABA_CHECKOUTS": "",
            # never let the fixture reach a real board-api
            "BOARD_API": "http://127.0.0.1:9",
        })

    def _run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(("bash", str(SCRIPT)), cwd=self.served,
                              text=True, capture_output=True, env=self.env,
                              timeout=180)

    def _pending_card(self, name: str) -> None:
        (self.served / "docs/ssot/kanban/cards" / name).write_text(
            f"title: {name}\n", encoding="utf-8")

    def _committed(self) -> str:
        return _git(self.served, "show", "--name-only", "--format=",
                    "HEAD").stdout

    def test_stale_age_lock_is_removed_and_commit_lands(self):
        # Lock older than KANBAN_INDEX_LOCK_STALE_S (900s) with no holder:
        # a crashed git's leftover. Must be cleared and the tick commit.
        self.lock.write_text("", encoding="utf-8")
        old = time.time() - 3600
        os.utime(self.lock, (old, old))
        self._pending_card("tick-stale-age.yml")

        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(self.lock.exists(),
                         "stale index.lock was not removed")
        self.assertIn("cleared stale index.lock", proc.stderr, proc.stderr)
        self.assertIn("docs/ssot/kanban/cards/tick-stale-age.yml",
                      self._committed())

    def test_stale_pid_lock_is_removed_even_when_fresh(self):
        # A recorded holder pid that is dead makes the lock stale
        # immediately — age is irrelevant (crash recovery, not a timer).
        pid = _dead_pid()
        self.lock.write_text(f"{pid}\n", encoding="utf-8")  # fresh mtime
        self._pending_card("tick-stale-pid.yml")

        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(self.lock.exists(),
                         "dead-pid index.lock was not removed")
        self.assertIn("cleared stale index.lock", proc.stderr, proc.stderr)
        self.assertIn("docs/ssot/kanban/cards/tick-stale-pid.yml",
                      self._committed())

    def test_live_lock_with_holder_is_left_alone(self):
        # Fresh lock + a live process holding it open (fuser-visible):
        # real git contention — the sweep must NOT remove it. Adds fail
        # their retries, nothing stages, the tick exits 0 and defers to
        # the next cycle.
        self.lock.write_text("", encoding="utf-8")
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import os, sys, time\n"
             "fd = os.open(sys.argv[1], os.O_RDONLY)\n"
             "time.sleep(120)\n",
             str(self.lock)])
        self.addCleanup(holder.kill)
        # wait until fuser can see the holder
        for _ in range(100):
            seen = subprocess.run(
                ["fuser", str(self.lock)], text=True,
                capture_output=True)
            if str(holder.pid) in seen.stdout:
                break
            time.sleep(0.1)
        else:
            self.fail("fuser never reported the lock holder")
        head_before = _git(self.served, "rev-parse", "HEAD").stdout.strip()
        self._pending_card("tick-live.yml")

        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(self.lock.exists(),
                        "live index.lock was wrongly removed")
        self.assertNotIn("cleared stale index.lock", proc.stderr,
                         proc.stderr)
        head_after = _git(self.served, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(head_before, head_after,
                         "tick committed despite the live lock")

    def test_fresh_lock_without_holder_is_left_alone(self):
        # Conservative default: a fresh lock whose holder can't be
        # identified (empty file, nobody holds it — e.g. fuser missing)
        # gets the benefit of the doubt until it ages past N. Pins the
        # "don't nuke fresh locks" half of the contract.
        self.lock.write_text("", encoding="utf-8")  # fresh mtime
        head_before = _git(self.served, "rev-parse", "HEAD").stdout.strip()
        self._pending_card("tick-fresh.yml")

        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(self.lock.exists(),
                        "fresh index.lock was wrongly removed")
        self.assertNotIn("cleared stale index.lock", proc.stderr,
                         proc.stderr)
        head_after = _git(self.served, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(head_before, head_after,
                         "tick committed despite the fresh lock")


if __name__ == "__main__":
    unittest.main()
