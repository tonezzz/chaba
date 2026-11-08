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
