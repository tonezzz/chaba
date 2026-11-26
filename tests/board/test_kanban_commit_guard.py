"""CI regression guard for kanban-commit's stale-write boundary.

Incidents 4af10b4c5c (staged scripts/board/*.py rode into a board commit)
and 56aac6476c (stale ssot.kanban.yml prose reverted the OPS-1406 restore)
were silent because `git commit` ran with no pathspec. The sweep must own
only generated board paths, and must refuse anything else staged — code,
deletions, or the hand-maintained prose.

The full tests/test-kanban-commit.sh suite has known fixture failures, so
this focused test runs the real script against a minimal scratch repo and
is safe to gate CI on.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/kanban-commit.sh"
CARD_IO = REPO / "scripts/board/card_io.py"
PROSE = "docs/ssot/kanban/ssot.kanban.yml"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("git", *args), cwd=cwd, text=True,
                          capture_output=True, check=True)


class KanbanCommitGuardTest(unittest.TestCase):
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
        (seed / "scripts/board").mkdir(parents=True)
        (seed / "docs/ssot/kanban/cards/.gitkeep").touch()
        (seed / PROSE).write_text("title: kanban\n", encoding="utf-8")
        shutil.copy2(CARD_IO, seed / "scripts/board/card_io.py")
        _git(seed, "add", "-A")
        _git(seed, "commit", "-qm", "seed")
        _git(seed, "push", "-q", "origin", "master")

        self.served = root / "served"
        _git(root, "clone", "-q", str(origin), str(self.served))
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            _git(self.served, "config", k, v)
        (self.served / "scripts/board").mkdir(parents=True, exist_ok=True)
        shutil.copy2(CARD_IO, self.served / "scripts/board/card_io.py")
        # idc03 has this generated dir on disk but with no tracked files.
        # A positive pathspec for it must not kill the sweep (20:30 incident).
        (self.served / "stacks/web/public/apps/board").mkdir(
            parents=True, exist_ok=True)

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
                              timeout=120)

    def test_commit_is_pathspec_limited_and_guard_checks_deletions(self):
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('-- "${COMMIT_PATHS[@]}"', src,
                      "board commit must be pathspec-limited")
        self.assertIn(':(exclude)${PROTECTED_PATH}', src,
                      "hand-maintained prose must be excluded at add/commit")
        self.assertIn('--diff-filter=ACMD', src,
                      "staged deletions must be guarded too")

    def test_staged_code_is_refused_and_never_committed(self):
        stale = self.served / "scripts/board/stale.py"
        stale.write_text("STALE CODE\n", encoding="utf-8")
        _git(self.served, "add", "scripts/board/stale.py")

        proc = self._run()
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("out-of-scope staged", proc.stderr, proc.stderr)
        committed = _git(self.served, "show", "--name-only",
                         "--format=", "HEAD").stdout
        self.assertNotIn("scripts/board/stale.py", committed, committed)

    def test_staged_prose_is_refused_and_never_committed(self):
        with (self.served / PROSE).open("a", encoding="utf-8") as fh:
            fh.write("\n# stale prose\n")
        _git(self.served, "add", PROSE)

        proc = self._run()
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("stale prose staged", proc.stderr, proc.stderr)
        committed = _git(self.served, "show", "--name-only",
                         "--format=", "HEAD").stdout
        self.assertNotIn(PROSE, committed, committed)

    def test_generated_card_still_commits_with_empty_generated_dirs(self):
        card = self.served / "docs/ssot/kanban/cards/regular.yml"
        card.write_text("title: regular\n", encoding="utf-8")

        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("did not match any file(s) known to git",
                         proc.stderr, proc.stderr)
        committed = _git(self.served, "show", "--name-only",
                         "--format=", "HEAD").stdout
        self.assertIn("docs/ssot/kanban/cards/regular.yml", committed, committed)

    def test_large_generated_path_survives_pipefail(self):
        # Regression (idc03 20:54): `git ls-files -- docs/ssot/ | grep -q .`
        # looks right but under `set -o pipefail` grep -q closes the pipe
        # early on a large listing, git dies with SIGPIPE (141), and
        # docs/ssot/ silently drops out of COMMIT_PATHS — its staged card
        # edits then never commit while the sweep still exits 0.
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("| grep -q .", src,
                         "pipefail + grep -q drops large pathspecs via SIGPIPE")
        self.assertIn("--error-unmatch", src,
                      "pathspec presence must be checked without a pipe")

        bulk = self.served / "docs/ssot/bulk"
        bulk.mkdir(parents=True, exist_ok=True)
        for i in range(3000):
            (bulk / f"f{i:04d}.yml").write_text("x: 1\n", encoding="utf-8")
        _git(self.served, "add", "docs/ssot/bulk")
        card = self.served / "docs/ssot/kanban/cards/regular.yml"
        card.write_text("title: regular\n", encoding="utf-8")

        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        committed = _git(self.served, "show", "--name-only",
                         "--format=", "HEAD").stdout
        self.assertIn("docs/ssot/kanban/cards/regular.yml", committed, committed)


if __name__ == "__main__":
    unittest.main()
