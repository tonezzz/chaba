"""Tests for runner-agent._self_update's tooling-pin gate.

Card runner-agent-deploy-propagation-gap-repo-56a255 (OPS-1026 follow-up):
the snapshot fast-path installs whatever the host's chaba checkout holds,
but sync-runner-tools.sh refuses any source whose sha256 doesn't match
scripts/devin/runner-tooling.manifest.json. On 2026-11-24 commit
7dc2187b7d changed runner-agent.py without a pin bump — _self_update
propagated the unpinned build while the sync path refused it, leaving the
two deploy paths disagreeing about what "current" means. _self_update now
applies the same pin check before installing.

Hermetic: a fake $HOME with .local/bin/runner-agent as the "installed"
snapshot and a fake chaba checkout wired through $DISPATCH_DIR/repos.conf.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "board" / "runner-agent.py"
SRC_REL = "scripts/board/runner-agent.py"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _load_from(path: Path, name: str):
    # SourceFileLoader: the installed snapshot has no .py extension, so
    # spec_from_file_location alone can't pick a loader for it.
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class SelfUpdatePinGateTest(unittest.TestCase):
    """Each test builds: tmp/home/.local/bin/runner-agent (snapshot) +
    tmp/repo/scripts/{board/runner-agent.py,devin/manifest} + repos.conf."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ra-selfupd-"))
        self.home = self.tmp / "home"
        self.snap = self.home / ".local/bin/runner-agent"
        self.snap.parent.mkdir(parents=True)
        self.repo = self.tmp / "repo"
        (self.repo / "scripts/board").mkdir(parents=True)
        (self.repo / "scripts/devin").mkdir(parents=True)
        self.src = self.repo / SRC_REL
        self.manifest = (self.repo / "scripts/devin"
                         / "runner-tooling.manifest.json")
        ddir = self.home / ".local/share/devin-dispatch"
        ddir.mkdir(parents=True)
        (ddir / "repos.conf").write_text(f"chaba {self.repo} master\n")
        # installed snapshot = current repo file minus a marker, older mtime
        base = SCRIPT.read_bytes()
        self.snap.write_bytes(base + b"\n# snapshot-v1\n")
        os.utime(self.snap, (1_000_000, 1_000_000))
        # repo source = snapshot content + a different marker ("v2")
        self.v2 = base + b"\n# repo-v2\n"
        self.src.write_bytes(self.v2)
        os.utime(self.src, (2_000_000, 2_000_000))
        self._env = mock.patch.dict(os.environ, {
            "HOME": str(self.home),
            "DISPATCH_DIR": str(ddir),
        })
        self._env.start()
        self._execv = mock.patch("os.execv")
        self.execv = self._execv.start()
        # module __file__ must BE the snapshot for the snapshot predicate
        self.mod = _load_from(self.snap, "runner_agent_snap")

    def tearDown(self):
        self._execv.stop()
        self._env.stop()

    def _write_manifest(self, pin: str):
        self.manifest.write_text(json.dumps({"tools": {"runner_agent": {
            "source": SRC_REL, "dest": "runner-agent",
            "sha256": pin}}}))

    def _run(self):
        self.mod._self_update()

    def test_pinned_newer_source_self_installs_and_reexecs(self):
        self._write_manifest(_sha(self.v2))
        self._run()
        self.assertEqual(self.snap.read_bytes(), self.v2)
        self.execv.assert_called_once()
        argv = self.execv.call_args[0][1]
        self.assertEqual(Path(argv[1]).resolve(), self.snap.resolve())

    def test_unpinned_source_refused(self):
        # pin points at some other build — the 2026-11-24 master state
        self._write_manifest(_sha(b"some-other-build"))
        before = self.snap.read_bytes()
        self._run()
        self.assertEqual(self.snap.read_bytes(), before)
        self.execv.assert_not_called()

    def test_missing_manifest_refused(self):
        before = self.snap.read_bytes()
        self._run()
        self.assertEqual(self.snap.read_bytes(), before)
        self.execv.assert_not_called()

    def test_older_source_never_downgrades(self):
        self._write_manifest(_sha(self.v2))
        os.utime(self.src, (500_000, 500_000))   # src older than snapshot
        before = self.snap.read_bytes()
        self._run()
        self.assertEqual(self.snap.read_bytes(), before)
        self.execv.assert_not_called()

    def test_identical_source_noop(self):
        # snapshot already equals the pinned repo copy
        self.snap.write_bytes(self.v2)
        os.utime(self.snap, (1_000_000, 1_000_000))
        self._write_manifest(_sha(self.v2))
        self._run()
        self.execv.assert_not_called()

    def test_repo_checkout_run_is_noop(self):
        # module loaded from the repo path, not the snapshot -> early return
        mod = _load_from(self.src, "runner_agent_repo")
        self._write_manifest(_sha(self.v2))
        mod._self_update()
        self.execv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
