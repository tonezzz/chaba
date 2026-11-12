import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import json

os.environ["BOARD_API_COMMIT"] = "0"

REPO = Path(__file__).resolve().parents[2]

def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "board" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class QueueClassifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos")
        cls.api = _load("board-api")
        cls.api.dr = cls.dr

    def setUp(self):
        self.api.CARD_DIR = Path("/tmp/nonexistent")
        self.api.now = lambda: "2026-10-31T00:00:00Z"
        self.api.comms_add = lambda card, frm, text: card.setdefault("comms", []).append({"from": frm, "text": text})
        self.api.save = lambda p, c: None
        self.api.queue_starve_warn = lambda c: ""
        self.api.queue_unclaimable_warn = lambda c: ""
        self.api.HOST = "localhost"

    def test_kw_hit(self):
        card = {"id": "c1", "title": "remove unused config", "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "codemod")
        self.assertIn("classified as codemod", card["comms"][0]["text"])
        self.assertEqual(card["action"]["status"], "queued")
        self.assertTrue(res.startswith("queued"))

    @patch("urllib.request.urlopen")
    def test_jevos_down_fallback(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("jevos down")
        card = {"id": "c1", "title": "Random ambiguous thing", "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "devin")
        self.assertIn("fallback conf 0.00", card["comms"][0]["text"])

    def test_explicit_action_model_wins(self):
        card = {"id": "c1", "title": "remove unused config", "action": {"model": "my-custom-model"}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "codemod")
        self.assertEqual(card["action"]["model"], "my-custom-model")

    def test_manual_refuses(self):
        card = {"id": "c1", "title": "hardware rotation", "action": {}}
        res = self.api.do_action(card, "queue", "devin")
        self.assertEqual(card["action"]["lane"], "manual")
        self.assertEqual(card["action"].get("status"), "idle")
        self.assertEqual(res, "classified as manual — queue skipped")

if __name__ == "__main__":
    unittest.main()
