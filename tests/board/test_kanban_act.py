"""Tests for kanban-act (scripts/ada/kanban-act.py — card kanban-act-loop).

Covers the eligibility gates (review-column only, review_kind=decide hold,
open requests/ask hold) and the verified_true + git_merged checks.
git_merged is exercised against a real bare origin + clone built in a
tmpdir — no network, no systemd.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "kanban_act", REPO / "scripts" / "ada" / "kanban-act.py")
ka = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ka)


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True)


class TestGateHoldReason(unittest.TestCase):
    def test_review_card_no_requests_passes(self):
        self.assertIsNone(ka.gate_hold_reason({"column": "review"}))

    def test_non_review_columns_hold(self):
        for col in ("backlog", "doing", "lab"):
            r = ka.gate_hold_reason({"column": col})
            self.assertIsNotNone(r, col)
            self.assertIn("column", r)

    def test_review_kind_decide_holds(self):
        r = ka.gate_hold_reason(
            {"column": "review", "review_kind": "decide"})
        self.assertIsNotNone(r)
        self.assertIn("decide", r)

    def test_review_kind_verify_passes(self):
        self.assertIsNone(ka.gate_hold_reason(
            {"column": "review", "review_kind": "verify"}))

    def test_open_request_holds(self):
        card = {"column": "review",
                "requests": [{"id": "q1", "ask": "ok?", "status": "open"}]}
        r = ka.gate_hold_reason(card)
        self.assertIsNotNone(r)
        self.assertIn("q1", r)

    def test_answered_request_passes(self):
        card = {"column": "review",
                "requests": [{"id": "q1", "ask": "ok?",
                              "status": "answered", "answer": "yes"}]}
        self.assertIsNone(ka.gate_hold_reason(card))

    def test_open_ask_holds(self):
        card = {"column": "review",
                "ask": {"question": "pick one", "options": ["a", "b"]}}
        r = ka.gate_hold_reason(card)
        self.assertIsNotNone(r)
        self.assertIn("ask", r)

    def test_answered_ask_passes(self):
        card = {"column": "review",
                "ask": {"question": "pick one", "status": "answered",
                        "answer": "a"}}
        self.assertIsNone(ka.gate_hold_reason(card))


class TestVerifiedTrue(unittest.TestCase):
    def setUp(self):
        self.cards = {
            "act-verified": {"id": "act-verified",
                             "action": {"verified": True}},
            "act-false": {"id": "act-false",
                          "action": {"verified": False}},
            "top-string": {"id": "top-string",
                           "verified": "auto 2026-10-08T15:30+00:00"},
            "top-false": {"id": "top-false", "verified": "false"},
            "none": {"id": "none"},
        }

    def test_action_verified_true(self):
        self.assertTrue(ka.check_verified_true("", self.cards,
                                               self.cards["act-verified"]))

    def test_action_verified_false(self):
        self.assertFalse(ka.check_verified_true("", self.cards,
                                                self.cards["act-false"]))

    def test_toplevel_string_stamp(self):
        self.assertTrue(ka.check_verified_true("top-string", self.cards))

    def test_toplevel_false_string(self):
        self.assertFalse(ka.check_verified_true("top-false", self.cards))

    def test_absent_flag_and_missing_card(self):
        self.assertFalse(ka.check_verified_true("none", self.cards))
        self.assertFalse(ka.check_verified_true("ghost", self.cards))


class TestGitMerged(unittest.TestCase):
    """Real-git fixture: bare origin + clone. feat-merged lands on
    master; feat-open stays unmerged."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        t = Path(cls._tmp.name)
        cls.origin = t / "origin.git"
        cls.work = t / "work"
        _git(t, "init", "--bare", str(cls.origin))
        _git(t, "clone", str(cls.origin), str(cls.work))
        for cfg in (("user.email", "t@t"), ("user.name", "t"),
                    ("init.defaultBranch", "master")):
            _git(cls.work, "config", *cfg)
        (cls.work / "f.txt").write_text("base\n")
        _git(cls.work, "add", ".")
        _git(cls.work, "commit", "-m", "base")
        _git(cls.work, "push", "origin", "master")
        # merged branch
        _git(cls.work, "checkout", "-b", "feat-merged")
        (cls.work / "f.txt").write_text("merged\n")
        _git(cls.work, "commit", "-am", "merged work")
        _git(cls.work, "push", "origin", "feat-merged")
        _git(cls.work, "checkout", "master")
        _git(cls.work, "merge", "--no-ff", "feat-merged", "-m", "merge")
        _git(cls.work, "push", "origin", "master")
        # open branch
        _git(cls.work, "checkout", "-b", "feat-open")
        (cls.work / "f.txt").write_text("open\n")
        _git(cls.work, "commit", "-am", "open work")
        _git(cls.work, "push", "origin", "feat-open")

        cls._old_repo = ka.REPO
        ka.REPO = cls.work

    @classmethod
    def tearDownClass(cls):
        ka.REPO = cls._old_repo
        cls._tmp.cleanup()

    def test_merged_prefix(self):
        self.assertTrue(ka.check_git_merged("feat-merged", {}))

    def test_unmerged_prefix(self):
        self.assertFalse(ka.check_git_merged("feat-open", {}))

    def test_prefix_covers_siblings(self):
        # feat-* matches both heads; one is unmerged -> fail
        self.assertFalse(ka.check_git_merged("feat-", {}))

    def test_no_matching_branch(self):
        self.assertFalse(ka.check_git_merged("ghost-branch", {}))

    def test_ref_injection_rejected(self):
        for bad in ("..", "a;b", "a b", "--upload-pack=x", "a$(id)"):
            self.assertFalse(ka.check_git_merged(bad, {}), bad)


if __name__ == "__main__":
    unittest.main()
