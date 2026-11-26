"""Unit tests for POST /wp-comment — the comment->work loop-close door
(card lesson-comments-dev-board): an agent that actioned a member
comment replies in-thread on WP under its own identity (devin|ada|
chaba) via per-identity app passwords in wp-agent-users.env.

Covers validation, the from/as identity gate, payload shape (parent
threading + status=approve), and the agent= seam handed to wp_api.
wp_api is patched — no network, no WP.
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

os.environ["BOARD_API_COMMIT"] = "0"

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / "board" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeWP:
    """Records wp_api calls; returns a canned comment object."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else {
            "id": 777, "status": "approved",
            "link": "https://boards.surf-thailand.com/wp/lesson/x/#comment-777"}

    def __call__(self, route, data=None, method=None, agent=None):
        self.calls.append({"route": route, "data": data,
                           "method": method, "agent": agent})
        return self.result


class WpCommentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load("board-api.py")

    def setUp(self):
        self.wp = FakeWP()
        self._orig_wp_api = self.mod.wp_api
        self.mod.wp_api = self.wp

    def tearDown(self):
        self.mod.wp_api = self._orig_wp_api

    # -- validation ---------------------------------------------------------

    def test_post_required(self):
        with self.assertRaises(ValueError):
            self.mod.do_wp_comment({"content": "hi", "as": "devin"},
                                   "devin")
        with self.assertRaises(ValueError):
            self.mod.do_wp_comment({"post": "abc", "content": "hi",
                                    "as": "devin"}, "devin")

    def test_content_required(self):
        with self.assertRaises(ValueError):
            self.mod.do_wp_comment({"post": 2040, "as": "devin"}, "devin")
        with self.assertRaises(ValueError):
            self.mod.do_wp_comment({"post": 2040, "content": "   ",
                                    "as": "devin"}, "devin")

    def test_as_must_be_known_identity(self):
        for bad in ("", "root", "admin", "DEVIN2"):
            with self.assertRaises(ValueError, msg=bad):
                self.mod.do_wp_comment(
                    {"post": 1, "content": "x", "as": bad}, "tony")

    # -- identity gate --------------------------------------------------------

    def test_agent_can_only_speak_as_itself(self):
        with self.assertRaises(ValueError):
            self.mod.do_wp_comment(
                {"post": 1, "content": "x", "as": "ada"}, "devin")
        with self.assertRaises(ValueError):
            self.mod.do_wp_comment(
                {"post": 1, "content": "x", "as": "chaba"}, "ada")

    def test_agent_as_self_ok(self):
        r = self.mod.do_wp_comment(
            {"post": 1, "content": "done", "as": "devin"}, "devin")
        self.assertEqual(r["as"], "devin")

    def test_tony_and_local_may_use_any_identity(self):
        for frm in ("tony", "chaba"):
            r = self.mod.do_wp_comment(
                {"post": 1, "content": "sys", "as": "ada"}, frm)
            self.assertEqual(r["as"], "ada")

    # -- payload + seam --------------------------------------------------------

    def test_payload_threads_and_approves(self):
        self.mod.do_wp_comment(
            {"post": 2040, "parent": 991, "content": "fixed — see card",
             "as": "devin"}, "devin")
        call = self.wp.calls[0]
        self.assertEqual(call["route"], "/wp/v2/comments")
        self.assertEqual(call["agent"], "devin")
        self.assertEqual(call["data"], {
            "post": 2040, "parent": 991,
            "content": "fixed — see card", "status": "approve"})

    def test_parent_optional(self):
        self.mod.do_wp_comment(
            {"post_id": 5, "text": "top-level", "as": "chaba"}, "chaba")
        data = self.wp.calls[0]["data"]
        self.assertNotIn("parent", data)
        self.assertEqual(data["post"], 5)

    def test_response_carries_comment_id(self):
        r = self.mod.do_wp_comment(
            {"post": 1, "content": "x", "as": "devin"}, "devin")
        self.assertEqual(r["comment_id"], 777)
        self.assertEqual(r["status"], "approved")

    def test_remote_dispatch_routes_wp_comment(self):
        r = self.mod._remote_dispatch(
            "/wp-comment",
            {"post": 9, "content": "hi", "as": "ada"}, "ada")
        self.assertEqual(r["as"], "ada")
        self.assertEqual(self.wp.calls[0]["agent"], "ada")


if __name__ == "__main__":
    unittest.main()
