"""Unit tests for the dev-board lane in wp-comment-sync (card
lesson-comments-dev-board): digest-bound comments (lesson/CMS posts,
cam/bench/render_job, unknown types) are classified
actionable|discussion|question — actionable files a kanban card via
board-api POST /card (id wpc-<comment_id>, column backlog, spec with
post_id+comment_id+permalink), question files the questions queue,
discussion stays digest-only. Agent-authored comments are never
re-routed. No network — _litellm_chat/board_api_post/api patched.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


wcs = load("wp_comment_sync", "scripts/ada/wp-comment-sync.py")


def comment(cid=101, text="please fix the typo", author="Tony",
            post=2040, ctype="lesson"):
    return {
        "id": cid,
        "post": post,
        "author": 7,
        "author_name": author,
        "date": "2026-11-26T10:00:00",
        "date_gmt": "2026-11-26T03:00:00",
        "content": {"rendered": f"<p>{text}</p>"},
    }


def post_obj(pid=2040, ptype="lesson", title="Lesson — DNS"):
    # post_ref() normalizes title to a plain string
    return {"id": pid, "type": ptype, "slug": "x", "title": title,
            "link": f"https://x/wp/{ptype}/{pid}/", "meta": {}}


class FakeChat:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def chat(self, prompt, **kw):
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class BoardLaneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._patches = [
            patch.object(wcs, "STATE_DIR", Path(self.tmp.name)),
            patch.object(wcs, "STATE", Path(self.tmp.name) / "state.json"),
            patch.object(wcs, "DIGEST", Path(self.tmp.name) / "digest.jsonl"),
            patch.object(wcs, "QUESTION_DIR",
                         Path(self.tmp.name) / "questions"),
            patch.object(wcs, "CORR_DIR",
                         Path(self.tmp.name) / "record-corrections"),
            patch.object(wcs, "EVENTS_FILE",
                         Path(self.tmp.name) / "events.md"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        self.card_calls = []
        self._bp = patch.object(
            wcs, "board_api_post",
            side_effect=lambda path, payload, **kw: (
                self.card_calls.append((path, payload)) or
                {"ok": True, "id": payload.get("id")}))
        self._bp.start()
        self.addCleanup(self._bp.stop)
        # no agent identities configured in tests
        self._ae = patch.object(wcs, "_load_agent_env", return_value={})
        self._ae.start()
        self.addCleanup(self._ae.stop)
        # chat-local classifier stub — tests set self.chat.reply
        self.chat = FakeChat("discussion")
        self._lc = patch.object(wcs, "_litellm_chat",
                                return_value=self.chat)
        self._lc.start()
        self.addCleanup(self._lc.stop)

    def classify(self, reply):
        self.chat.reply = reply
        return self.chat

    # -- classify_board_intent ----------------------------------------------

    def test_classify_actionable(self):
        self.classify("actionable")
        c, p = comment(), post_obj()
        self.assertEqual(wcs.classify_board_intent(c, p), "actionable")

    def test_classify_question_and_discussion(self):
        for reply, want in (("question", "question"),
                            ("discussion", "discussion"),
                            ("ACTIONABLE.", "actionable"),
                            ("garbage words here", "discussion"),
                            ("", "discussion")):
            self.classify(reply)
            self.assertEqual(
                wcs.classify_board_intent(comment(), post_obj()), want,
                msg=reply)

    def test_classify_disabled_and_tiny(self):
        with patch.dict(os.environ, {"WCS_BOARD_CLASSIFY": "0"}):
            self.assertEqual(
                wcs.classify_board_intent(comment(), post_obj()),
                "discussion")
        chat = self.classify("actionable")
        tiny = comment(text="ok")
        self.assertEqual(wcs.classify_board_intent(tiny, post_obj()),
                         "discussion")
        self.assertEqual(chat.prompts, [])   # never called for <3 chars

    def test_classify_failure_defaults_discussion(self):
        self.classify(RuntimeError("litellm down"))
        self.assertEqual(
            wcs.classify_board_intent(comment(), post_obj()),
            "discussion")

    # -- file_board_card ------------------------------------------------------

    def test_actionable_files_card(self):
        c, p = comment(cid=555, text="the diagram is wrong, please redo"), \
            post_obj()
        qid = wcs.file_board_card(c, p, dry_run=False)
        self.assertEqual(qid, "card:wpc-555")
        path, payload = self.card_calls[0]
        self.assertEqual(path, "/card")
        self.assertEqual(payload["id"], "wpc-555")
        self.assertEqual(payload["column"], "backlog")
        self.assertIn("post_id: 2040", payload["spec"])
        self.assertIn("comment_id: 555", payload["spec"])
        self.assertIn("#comment-555", payload["spec"])
        self.assertIn("/wp-comment", payload["spec"])

    def test_card_dedup_on_already_exists(self):
        import urllib.error
        self._bp.stop()
        err = urllib.error.HTTPError(
            "u", 400, "bad", {}, None)
        err.read = lambda: b'{"error": "card wpc-9 already exists"}'
        with patch.object(wcs, "board_api_post", side_effect=err):
            qid = wcs.file_board_card(comment(cid=9), post_obj(),
                                      dry_run=False)
        self.assertEqual(qid, "card:wpc-9")

    def test_card_error_returned(self):
        import urllib.error
        self._bp.stop()
        err = urllib.error.HTTPError("u", 500, "x", {}, None)
        err.read = lambda: b"boom"
        with patch.object(wcs, "board_api_post", side_effect=err):
            qid = wcs.file_board_card(comment(cid=9), post_obj(),
                                      dry_run=False)
        self.assertEqual(qid, "card:error:9")

    def test_card_dry_run_no_post(self):
        qid = wcs.file_board_card(comment(cid=1), post_obj(),
                                  dry_run=True)
        self.assertEqual(qid, "card:wpc-1")
        self.assertEqual(self.card_calls, [])

    # -- route() integration ---------------------------------------------------

    def test_route_actionable_gives_board_lane(self):
        self.classify("actionable")
        lane, qid = wcs.route(comment(cid=42), post_obj(), dry_run=False)
        self.assertEqual(lane, wcs.LANE_BOARD)
        self.assertEqual(qid, "card:wpc-42")
        self.assertEqual(len(self.card_calls), 1)
        # digest record carries the class
        rec = json.loads(
            (Path(self.tmp.name) / "digest.jsonl").read_text()
            .strip().splitlines()[-1])
        self.assertEqual(rec["lane"], "board")
        self.assertEqual(rec["class"], "actionable")
        self.assertEqual(rec["card"], "card:wpc-42")

    def test_route_question_files_queue(self):
        self.classify("question")
        lane, qid = wcs.route(comment(cid=43, text="what does this mean?"),
                              post_obj(), dry_run=False)
        self.assertEqual(lane, wcs.LANE_QUESTION)
        self.assertEqual(qid, "question:43")
        qf = Path(self.tmp.name) / "questions" / "q-43.yml"
        self.assertTrue(qf.exists())
        # questions go to the focus inbox, never to a kanban card
        self.assertEqual([p for p, _ in self.card_calls], ["/inbox"])
        inbox_body = self.card_calls[0][1]
        self.assertIn("comment_id: 43", inbox_body["text"])
        self.assertIn("/wp-comment", inbox_body["text"])

    def test_route_discussion_stays_digest(self):
        self.classify("discussion")
        lane, qid = wcs.route(comment(cid=44), post_obj(), dry_run=False)
        self.assertEqual(lane, wcs.LANE_DIGEST)
        self.assertEqual(qid, "digest:44")
        self.assertEqual(self.card_calls, [])
        rec = json.loads(
            (Path(self.tmp.name) / "digest.jsonl").read_text()
            .strip().splitlines()[-1])
        self.assertEqual(rec["class"], "discussion")

    def test_route_non_digest_lanes_unaffected(self):
        """memory-mirror/asset/news lanes must not hit the board classify."""
        chat = self.classify("actionable")
        lane, qid = wcs.route(comment(cid=45),
                              post_obj(ptype="memory-mirror"),
                              dry_run=True)
        self.assertEqual(lane, wcs.LANE_ADA)
        self.assertEqual(chat.prompts, [])

    # -- agent comments never re-routed ----------------------------------------

    def test_is_agent_comment_by_id(self):
        with patch.object(wcs, "agent_user_ids", return_value={99}):
            c = comment()
            c["author"] = 99
            self.assertTrue(wcs.is_agent_comment(c))
            c["author"] = 7
            self.assertFalse(wcs.is_agent_comment(c))

    def test_is_agent_comment_by_name(self):
        for name in ("Devin", "ada", "Chaba (agent)", "DEVIN"):
            c = comment(author=name)
            self.assertTrue(wcs.is_agent_comment(c), msg=name)
        self.assertFalse(wcs.is_agent_comment(comment(author="Tony")))
        self.assertFalse(wcs.is_agent_comment(comment(author="member1")))

    # -- ack texts ---------------------------------------------------------------

    def test_ack_board_filed_mentions_card(self):
        captured = {}

        def fake_api(method, route, data=None, auth=None):
            captured.update(data or {})
            captured["auth"] = auth
            return 201, {"id": 900}

        with patch.object(wcs, "api", side_effect=fake_api), \
                patch.object(wcs, "agent_basic_auth", return_value=None):
            ack_id = wcs.ack(comment(cid=50), wcs.LANE_BOARD,
                             "card:wpc-50", dry_run=False)
        self.assertEqual(ack_id, 900)
        self.assertIn("wpc-50", captured["content"])
        self.assertIn(wcs.ACK_MARK, captured["content"])
        self.assertEqual(captured["parent"], 50)

    def test_ack_board_error_and_question(self):
        with patch.object(wcs, "api", return_value=(201, {"id": 1})), \
                patch.object(wcs, "agent_basic_auth", return_value=None):
            wcs.ack(comment(cid=51), wcs.LANE_BOARD,
                    "card:error:51", dry_run=False)
            wcs.ack(comment(cid=52), wcs.LANE_QUESTION,
                    "question:52", dry_run=False)

    def test_ack_posts_as_agent_identity_when_present(self):
        seen = {}

        def fake_api(method, route, data=None, auth=None):
            seen["auth"] = auth
            return 201, {"id": 5}

        with patch.object(wcs, "api", side_effect=fake_api), \
                patch.object(wcs, "agent_basic_auth",
                             return_value="Basic AGENT"):
            wcs.ack(comment(cid=53), wcs.LANE_DIGEST, "digest:53",
                    dry_run=False)
        self.assertEqual(seen["auth"], "Basic AGENT")


if __name__ == "__main__":
    unittest.main()
