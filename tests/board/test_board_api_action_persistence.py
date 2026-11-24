"""Regression tests for persisted /action mutations (KNB-1196).

These exercise the HTTP handler because pure do_claim tests cannot catch a
handler that mutates the loaded card but forgets to save it.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "board_api_action_persistence", REPO / "scripts" / "board" / "board-api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ActionPersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cards = Path(self.tmp.name) / "cards"
        self.cards.mkdir()
        self._old_card_dir = self.mod.CARD_DIR
        self._old_lock = self.mod.LOCK
        self._old_render = self.mod.render_async
        self.mod.CARD_DIR = self.cards
        self.mod.LOCK = Path(self.tmp.name) / "board-api.lock"
        self.mod.render_async = lambda: None
        self.commit_patch = patch.dict("os.environ", {"BOARD_API_COMMIT": "0"})
        self.commit_patch.start()
        # keep do_action deterministic — no lane classification, no
        # fleet/probe warnings leaking into the fingerprint surface
        self._cls_patch = patch.object(
            self.mod, "BOARD_CLASSIFY_AT_QUEUE", False)
        self._warn_patch = patch.object(
            self.mod, "queue_unclaimable_warn", lambda c: "")
        self._cls_patch.start()
        self._warn_patch.start()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.mod.H)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.commit_patch.stop()
        self._cls_patch.stop()
        self._warn_patch.stop()
        self.mod.CARD_DIR = self._old_card_dir
        self.mod.LOCK = self._old_lock
        self.mod.render_async = self._old_render
        self.tmp.cleanup()

    def write_card(self, card):
        path = self.cards / f"{card['id']}.yml"
        path.write_text(yaml.safe_dump(card, sort_keys=False))
        return path

    def post_action(self, body):
        request = urllib.request.Request(
            f"{self.base_url}/action",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_concurrent_claims_have_one_persisted_winner(self):
        path = self.write_card({
            "id": "claim-race",
            "title": "Claim race",
            "column": "backlog",
            "action": {"type": "dispatch", "status": "queued"},
        })

        start = threading.Barrier(2)

        def claim(host):
            start.wait(timeout=5)
            status, body = self.post_action({
                "id": "claim-race", "do": "claim", "host": host})
            return host, status, body

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ("macbook", "idc02")))

        self.assertCountEqual([status for _, status, _ in results],
                              [200, 400])
        claimed = yaml.safe_load(path.read_text())
        self.assertEqual(claimed["action"]["status"], "running")
        self.assertIn(claimed["action"]["runner"], ("macbook", "idc02"))
        loser = next(body for _, status, body in results if status == 400)
        self.assertIn("not claimable", loser["error"])

    def test_finish_is_saved(self):
        path = self.write_card({
            "id": "finish-persistence",
            "title": "Finish persistence",
            "column": "doing",
            "action": {
                "type": "dispatch", "status": "running", "runner": "idc02",
            },
        })

        status, _ = self.post_action({
            "id": "finish-persistence", "do": "finish", "host": "idc02",
            "ok": True, "result": "completed",
        })

        self.assertEqual(status, 200)
        finished = yaml.safe_load(path.read_text())
        self.assertEqual(finished["action"]["status"], "done")
        self.assertEqual(finished["column"], "review")

    def test_move_is_saved(self):
        path = self.write_card({
            "id": "move-persistence",
            "title": "Move persistence",
            "column": "backlog",
        })

        status, _ = self.post_action({
            "id": "move-persistence", "do": "move", "column": "review",
        })

        self.assertEqual(status, 200)
        moved = yaml.safe_load(path.read_text())
        self.assertEqual(moved["column"], "review")

    # ------------------------------------------- verify-or-loud
    # Card board-api-queue-write-verify-lost-race-f85f2f: /action
    # answers used to fire before the queued commit proved the write
    # durable — an autostash pop could already have reverted the card
    # (the OPS-0200 'queued' that never persisted). do:queue|retry|
    # close|hold now flush + re-read + fingerprint before answering;
    # a proven revert re-applies once, anything unproven answers 503.

    def test_queue_verified_in_response(self):
        path = self.write_card({
            "id": "queue-verify",
            "title": "Queue verify",
            "column": "backlog",
            "action": {"type": "dispatch", "status": "idle"},
        })

        status, body = self.post_action({"id": "queue-verify",
                                         "do": "queue"})

        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("verified"), body)
        card = yaml.safe_load(path.read_text())
        self.assertEqual(card["action"]["status"], "queued")

    def test_verify_reapply_after_lost_write(self):
        # the autostash-pop loss shape: disk still shows the PRE-write
        # fingerprint while `after` expects the queued mutation —
        # verify re-applies once under the flock and proves it landed
        path = self.write_card({
            "id": "queue-lost",
            "title": "Queue lost",
            "column": "backlog",
            "action": {"type": "dispatch", "status": "idle"},
        })
        card = yaml.safe_load(path.read_text())
        before = self.mod._action_fp(card)
        self.mod.do_action(card, "queue", "tony")   # in-memory only
        after = self.mod._action_fp(card)
        self.assertNotEqual(before, after)
        # disk untouched = the "eaten" write the pop left behind
        v = {"path": path, "verb": "queue", "frm": "tony",
             "before": before, "after": after}
        res = self.mod.verify_action_write(v)
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["reapplied"], res)
        disk = yaml.safe_load(path.read_text())
        self.assertEqual(disk["action"]["status"], "queued")

    def test_verify_reports_unverified_on_concurrent_state(self):
        # a third state (concurrent writer) must NOT be stomped and must
        # surface as failure — the HTTP layer answers 503 for it
        path = self.write_card({
            "id": "queue-raced",
            "title": "Queue raced",
            "column": "backlog",
            "action": {"type": "dispatch", "status": "idle"},
        })
        card = yaml.safe_load(path.read_text())
        before = self.mod._action_fp(card)
        self.mod.do_action(card, "queue", "tony")
        after = self.mod._action_fp(card)
        # a concurrent writer moved the card somewhere else entirely
        other = yaml.safe_load(path.read_text())
        other["column"] = "review"
        other["action"]["status"] = "running"
        path.write_text(yaml.safe_dump(other, sort_keys=False))
        v = {"path": path, "verb": "queue", "frm": "tony",
             "before": before, "after": after}
        res = self.mod.verify_action_write(v)
        self.assertFalse(res["ok"], res)
        disk = yaml.safe_load(path.read_text())
        self.assertEqual(disk["action"]["status"], "running")
        self.assertEqual(disk["column"], "review")

    def test_action_verify_failure_answers_503(self):
        self.write_card({
            "id": "queue-loud",
            "title": "Queue loud",
            "column": "backlog",
            "action": {"type": "dispatch", "status": "idle"},
        })
        with patch.object(self.mod, "verify_action_write",
                          lambda v: {"ok": False, "error": "boom"}):
            status, body = self.post_action({"id": "queue-loud",
                                             "do": "queue"})
        self.assertEqual(status, 503, body)
        self.assertFalse(body.get("verified"))
        self.assertIn("boom", body["error"])
