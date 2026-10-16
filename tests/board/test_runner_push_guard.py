"""Unit tests for the runner-agent push-credential claim guard
(card runner-push-cred-gap — the 2026-10-14 ADA-0673 / idc03 daa0e0a
incident: runners claimed dispatches for repos their deploy key can't
push, stranding finished branches while cards read done+verified).

The guard: a dispatch card is only claimable when the host can push the
card's repo — `push:<repo>` label in RUNNER_LABELS is the declared fast
path, a live `git push --dry-run` probe is the ground truth, and
RUNNER_PUSH_GUARD=0 restores the pre-guard behavior.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _card(repo="ada-voice", **action_kw):
    a = {"type": "dispatch", "status": "queued", "repo": repo}
    a.update(action_kw)
    return {"id": "ada-card", "action": a}


class PushGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in
                       ("LABELS", "PUSH_GUARD", "DISPATCH")}
        self._saved_checkout = m._repo_checkout
        self._saved_sh = m.sh
        m.PUSH_GUARD = True
        m.LABELS = set()
        m._PUSH_PROBE_CACHE.clear()
        m.DISPATCH = str(SCRIPT)  # exists -> dispatch executor present
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo_dir = Path(self._td.name) / "repo"
        (self.repo_dir / ".git").mkdir(parents=True)

    def tearDown(self):
        m = self.mod
        for k, v in self._saved.items():
            setattr(m, k, v)
        m._repo_checkout = self._saved_checkout
        m.sh = self._saved_sh
        m._PUSH_PROBE_CACHE.clear()

    def test_declared_label_claims_without_probe(self):
        m = self.mod
        m.LABELS = {"push:ada-voice"}
        m.sh = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("probe ran despite declared label"))
        self.assertEqual(m.claimable(_card()), "dispatch")

    def test_alias_repo_needs_canonical_label(self):
        # action.repo: ada-pi cards check push:ada-voice — one repo,
        # one credential
        m = self.mod
        m.LABELS = {"push:ada-voice"}
        m.sh = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("probe ran despite declared label"))
        self.assertEqual(m.claimable(_card(repo="ada-pi")), "dispatch")

    def test_probe_ok_claims(self):
        m = self.mod
        m._repo_checkout = lambda r: self.repo_dir
        m.sh = lambda *a, **k: _proc(rc=0)
        self.assertEqual(m.claimable(_card()), "dispatch")
        # second card reuses the cached probe, not another dry-run
        self.assertEqual(m.claimable(_card()), "dispatch")

    def test_probe_failure_defers_and_explains(self):
        m = self.mod
        m._repo_checkout = lambda r: self.repo_dir
        calls = []

        def fake_sh(cmd, **k):
            calls.append(cmd)
            return _proc(rc=1, err="permission denied (deploykey)")
        m.sh = fake_sh
        self.assertEqual(m.claimable(_card()), "")
        self.assertEqual(len(calls), 1)
        self.assertIn("--dry-run", calls[0])
        reason = m.push_guard_reason(_card())
        self.assertIn("push:ada-voice", reason)
        self.assertIn("runner-push-cred-gap", reason)

    def test_missing_checkout_defers(self):
        m = self.mod
        m._repo_checkout = lambda r: None
        self.assertFalse(m.push_capable("ada-voice"))
        self.assertEqual(m.claimable(_card()), "")
        self.assertIn("no checkout", m.push_guard_reason(_card()))

    def test_guard_off_restores_old_behavior(self):
        m = self.mod
        m.PUSH_GUARD = False
        m.sh = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("probe ran with guard off"))
        self.assertEqual(m.claimable(_card()), "dispatch")

    def test_guard_does_not_apply_to_other_types(self):
        # container/script cards never consult push_capable
        m = self.mod
        m._repo_checkout = lambda r: None
        m.sh = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("push probe ran for a script card"))
        self.assertEqual(m.push_guard_reason(
            _card(type="script", script={"cmd": "true"})), "")

    def test_chaba_cards_are_guarded_too(self):
        # chaba is not exempt — a fetch-only chaba clone must not claim
        # chaba dispatches (the same stranding, default repo)
        m = self.mod
        m._repo_checkout = lambda r: None
        self.assertEqual(m.claimable(_card(repo="chaba")), "")
        self.assertIn("push:chaba", m.push_guard_reason(_card(repo="chaba")))


if __name__ == "__main__":
    unittest.main()
