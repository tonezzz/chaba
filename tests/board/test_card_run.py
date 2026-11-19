"""Tests for card-run.py — the card-runner eval loop (ada-card-runner
piece 4): per-attempt evaluation gates (changes -> normalize -> repo
validate -> declared verifier), the bounded-retry message contract,
and the bounded CI rollup surface.

No network, no board-api, no opencode — git repos are real tempdirs,
everything else is stubbed.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "board" / "card-run.py"


def _load():
    spec = importlib.util.spec_from_file_location("card_run", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(wt: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(wt), *argv],
                          capture_output=True, text=True)


def _mk_wt(tmp: Path) -> Path:
    """A real git worktree stand-in: master + origin/master ref."""
    wt = tmp / "wt"
    wt.mkdir()
    _git(wt, "init", "-q")
    _git(wt, "config", "user.email", "t@t")
    _git(wt, "config", "user.name", "t")
    (wt / "seed.txt").write_text("seed\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "seed")
    _git(wt, "branch", "-f", "origin/master", "HEAD")
    return wt


class CardRunHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_card_blocked_reason(self):
        m = self.mod
        done = {"column": "done", "action": {}}
        self.assertIn("done", m._card_blocked_reason(done, "h"))
        req = {"column": "backlog",
               "requests": [{"id": "r1", "status": "open"}],
               "action": {}}
        self.assertIn("open request",
                      m._card_blocked_reason(req, "h"))
        claimed = {"column": "backlog",
                   "action": {"status": "running",
                              "runner": "otherhost"}}
        self.assertIn("already claimed",
                      m._card_blocked_reason(claimed, "h"))
        ours = {"column": "backlog",
                "action": {"status": "running", "runner": "h.fqdn"}}
        self.assertIsNone(m._card_blocked_reason(ours, "h"))
        ok = {"column": "backlog", "action": {"status": "queued"}}
        self.assertIsNone(m._card_blocked_reason(ok, "h"))

    def test_retry_msg_carries_evidence(self):
        msg = self.mod.RETRY_MSG.format(n=2, total=3,
                                        evidence="verifier rc=1")
        self.assertIn("2/3", msg)
        self.assertIn("verifier rc=1", msg)


class PorcelainPathsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_modified_untracked_and_rename(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wt = _mk_wt(Path(td))
            (wt / "seed.txt").write_text("changed\n")
            (wt / "new.py").write_text("x = 1\n")
            _git(wt, "mv", "seed.txt", "renamed.txt")
            paths = self.mod._porcelain_paths(wt)
            self.assertIn("renamed.txt", paths)   # rename -> new name
            self.assertIn("new.py", paths)
            self.assertNotIn("seed.txt", paths)


class ValidateChangesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_clean_worktree_no_errors(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wt = _mk_wt(Path(td))
            self.assertEqual(self.mod._validate_changes(wt), [])

    def test_good_files_pass(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wt = _mk_wt(Path(td))
            (wt / "ok.py").write_text("x = 1\n")
            (wt / "ok.sh").write_text("#!/bin/bash\necho hi\n")
            (wt / "ok.json").write_text('{"a": 1}\n')
            (wt / "ok.yml").write_text("a: 1\n")
            self.assertEqual(self.mod._validate_changes(wt), [])

    def test_broken_files_flagged(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wt = _mk_wt(Path(td))
            (wt / "bad.py").write_text("def f(:\n")
            (wt / "bad.sh").write_text("if then fi\n")
            (wt / "bad.json").write_text("{oops\n")
            (wt / "bad.yml").write_text("a: [1,\nb: }\n")
            errs = self.mod._validate_changes(wt)
            joined = " | ".join(errs)
            for name in ("bad.py", "bad.sh", "bad.json", "bad.yml"):
                self.assertIn(name, joined)

    def test_no_pycache_litter(self):
        """compile() must not write __pycache__ into the worktree —
        it would be committed by the lifecycle's git add -A."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wt = _mk_wt(Path(td))
            (wt / "x.py").write_text("x = 1\n")
            self.mod._validate_changes(wt)
            self.assertFalse((wt / "__pycache__").exists())


class EvaluateAttemptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_no_changes_fails_with_evidence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wt = _mk_wt(Path(td))
            ok, evidence, notes, verified = \
                self.mod._evaluate_attempt(wt, "slug", None)
            self.assertFalse(ok)
            self.assertIn("no repo changes", evidence)
            self.assertFalse(verified)

    def test_good_change_passes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wt = _mk_wt(Path(td))
            _git(wt, "checkout", "-qb", "card/slug")
            (wt / "feat.py").write_text("x = 1\n")
            ok, evidence, notes, verified = \
                self.mod._evaluate_attempt(wt, "slug", None)
            self.assertTrue(ok, evidence)
            self.assertFalse(verified)   # no declared verifier

    def test_broken_change_fails_validate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wt = _mk_wt(Path(td))
            _git(wt, "checkout", "-qb", "card/slug")
            (wt / "feat.py").write_text("def f(:\n")
            ok, evidence, notes, verified = \
                self.mod._evaluate_attempt(wt, "slug", None)
            self.assertFalse(ok)
            self.assertIn("validate", evidence)
            self.assertIn("feat.py", evidence)

    def test_declared_verifier_gates_and_stamps(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wt = _mk_wt(Path(td))
            _git(wt, "checkout", "-qb", "card/slug")
            (wt / "feat.txt").write_text("hello\n")
            ok, ev, notes, verified = self.mod._evaluate_attempt(
                wt, "slug", "grep -q hello feat.txt")
            self.assertTrue(ok, ev)
            self.assertTrue(verified)
            ok, ev, notes, verified = self.mod._evaluate_attempt(
                wt, "slug", "grep -q missing feat.txt")
            self.assertFalse(ok)
            self.assertIn("verifier", ev)
            self.assertFalse(verified)


class CiWaitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def _stub(self, roll):
        calls = []
        def fake_sh(argv, cwd=None, timeout=120):
            calls.append(argv)
            return types.SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"statusCheckRollup": roll}),
                stderr="")
        return calls, fake_sh

    def test_skipped_when_zero(self):
        self.assertEqual(self.mod._ci_wait("u", Path("."), 0), "skipped")

    def test_pass(self):
        calls, fake = self._stub(
            [{"status": "COMPLETED", "conclusion": "SUCCESS",
              "name": "lint"}])
        m = self.mod
        old = m._sh
        m._sh = fake
        try:
            self.assertEqual(m._ci_wait("u", Path("."), 5), "pass")
        finally:
            m._sh = old

    def test_fail(self):
        calls, fake = self._stub(
            [{"status": "COMPLETED", "conclusion": "FAILURE",
              "name": "tests"}])
        m = self.mod
        old = m._sh
        m._sh = fake
        try:
            self.assertIn("fail", m._ci_wait("u", Path("."), 5))
            self.assertIn("tests", m._ci_wait("u", Path("."), 5))
        finally:
            m._sh = old

    def test_pending_times_out(self):
        calls, fake = self._stub(
            [{"status": "IN_PROGRESS", "conclusion": "",
              "name": "tests"}])
        m = self.mod
        old_sh, old_sleep = m._sh, m.time.sleep
        m._sh = fake
        m.time.sleep = lambda s: None
        try:
            self.assertIn("pending", m._ci_wait("u", Path("."), 1))
        finally:
            m._sh, m.time.sleep = old_sh, old_sleep

    def test_gh_error_is_unknown(self):
        m = self.mod
        old = m._sh
        m._sh = lambda *a, **k: types.SimpleNamespace(
            returncode=1, stdout="", stderr="boom")
        try:
            self.assertIn("unknown", m._ci_wait("u", Path("."), 5))
        finally:
            m._sh = old


if __name__ == "__main__":
    unittest.main()
