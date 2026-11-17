"""Unit tests for scripts/report-comms-narrate.py — the per-lane persona
narration of the comms digest (card narrated-comms-digest).

Covers the format contract ([<tag>] first line, <=10 lines, detail link)
and the never-silence rule (a model failure still posts a failure notice
on the lane's own channel). All LLM + HTTP calls faked — no network.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "report_comms_narrate", REPO / "scripts" / "report-comms-narrate.py")
rn = importlib.util.module_from_spec(spec)
sys.modules["report_comms_narrate"] = rn
spec.loader.exec_module(rn)

DIGEST = ("# Tony - Team Digest - Evening\n\n"
          "## Tony <-> Team (comms digest)\n\n"
          "### Your asks (2)\n\n- `card-a` [doing] - ship the thing\n"
          "- `card-b` [backlog] - look at X\n\n### Open loops (1)\n\n"
          "- `card-c` [doing] - unanswered ask\n")


class ComposeTest(unittest.TestCase):
    def test_tag_first_and_link_last(self):
        msg = rn.compose("ada", "Morning notes\nsecond line")
        lines = msg.splitlines()
        self.assertTrue(lines[0].startswith("[ada] "))
        self.assertIn("Morning notes", lines[0])
        self.assertIn(rn.PAGE_URL, lines[-1])

    def test_caps_at_max_lines(self):
        msg = rn.compose("ada", "\n".join(f"line {i}" for i in range(20)))
        self.assertLessEqual(len(msg.splitlines()), rn.MAX_LINES)

    def test_strips_model_tag_and_fences(self):
        msg = rn.compose("kaewta", "```\n[kaewta] สวัสดี\nลองดู\n```")
        self.assertTrue(msg.startswith("[kaewta] สวัสดี"))
        self.assertNotIn("```", msg)
        self.assertEqual(1, msg.count("[kaewta]"))

    def test_empty_text_still_valid(self):
        msg = rn.compose("ada", "   ")
        lines = msg.splitlines()
        self.assertTrue(lines[0].startswith("[ada]"))
        self.assertIn(rn.PAGE_URL, lines[-1])

    def test_kaewta_link_lede_is_thai(self):
        msg = rn.compose("kaewta", "สรุปวันนี้")
        self.assertTrue(msg.splitlines()[-1].startswith("ดูฉบับเต็ม:"))


class NarrateTest(unittest.TestCase):
    def test_prompt_carries_persona_and_digest(self):
        seen = {}

        def fake_chat(prompt, **kw):
            seen["prompt"] = prompt
            seen["model"] = kw.get("model")
            return "ok"
        with mock.patch.object(rn.litellm_chat, "chat", fake_chat):
            out = rn.narrate("ada", DIGEST, "evening")
        self.assertEqual(out, "ok")
        self.assertIn("Ada", seen["prompt"])
        self.assertIn("evening", seen["prompt"])
        self.assertIn("card-a", seen["prompt"])
        self.assertEqual(seen["model"], rn.MODEL)

    def test_model_failure_returns_none(self):
        with mock.patch.object(rn.litellm_chat, "chat",
                               lambda *a, **k: None):
            self.assertIsNone(rn.narrate("kaewta", DIGEST, "morning"))


class RunLaneTest(unittest.TestCase):
    def _run(self, lane, chat_ret, send_ret=True):
        sent = []

        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode())
            sent.append({"url": req.full_url, "body": body})
            return mock.MagicMock(status=200, __enter__=lambda s: s,
                                  __exit__=lambda *a: None)

        with mock.patch.object(rn.litellm_chat, "chat",
                               lambda *a, **k: chat_ret), \
             mock.patch.object(rn.urllib.request, "urlopen",
                               fake_urlopen):
            ok = rn.run_lane(lane, DIGEST, "evening", print_only=False)
        return ok, sent

    def test_send_posts_to_lane_listen(self):
        ok, sent = self._run("ada", "a short narration")
        self.assertTrue(ok)
        self.assertEqual(sent[0]["url"], "http://127.0.0.1:8911/send")
        text = sent[0]["body"]["text"]
        self.assertTrue(text.startswith("[ada] "))
        self.assertNotIn("chat_id", sent[0]["body"])

    def test_kaewta_lane_port(self):
        ok, sent = self._run("kaewta", "สรุป")
        self.assertTrue(ok)
        self.assertEqual(sent[0]["url"], "http://127.0.0.1:8913/send")

    def test_model_failure_posts_notice_not_silence(self):
        ok, sent = self._run("ada", None)
        self.assertTrue(ok)  # the failure notice itself sent fine
        self.assertIn("(digest narration failed", sent[0]["body"]["text"])


class CliTest(unittest.TestCase):
    def _main(self, argv, stdin=""):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["x"] + argv), \
             mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
             redirect_stdout(buf):
            rc = rn.main()
        return rc, buf.getvalue()

    def test_print_only_never_posts(self):
        calls = []
        with mock.patch.object(rn.litellm_chat, "chat",
                               lambda *a, **k: "hello lane"), \
             mock.patch.object(rn, "send",
                               lambda *a, **k: calls.append(a) or True):
            rc, out = self._main(["--stdin", "--print"], stdin=DIGEST)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertIn("[ada] hello lane", out)
        self.assertIn("[kaewta] hello lane", out)

    def test_empty_digest_narrates_nothing(self):
        with mock.patch.object(rn, "send") as s:
            rc, out = self._main(["--stdin", "--print"], stdin="  \n")
        self.assertEqual(rc, 0)
        s.assert_not_called()

    def test_pending_chaba_skipped(self):
        with mock.patch.object(rn.litellm_chat, "chat",
                               lambda *a, **k: "x"):
            rc, out = self._main(
                ["--stdin", "--print", "--lanes", "chaba,ada"],
                stdin=DIGEST)
        self.assertIn("skipped", out)
        self.assertIn("[ada]", out)

    def test_unknown_lane_warned(self):
        with mock.patch.object(rn.litellm_chat, "chat",
                               lambda *a, **k: "x"):
            rc, out = self._main(
                ["--stdin", "--print", "--lanes", "bogus"],
                stdin=DIGEST)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
