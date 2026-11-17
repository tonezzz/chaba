from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/kanban-dispatch.py"
sys.path.insert(0, str(REPO / "scripts" / "board"))


def _load():
    spec = importlib.util.spec_from_file_location("kanban_dispatch", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DispatchCardIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_unchanged_inactive_cards_are_not_reparsed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "cards"
            root.mkdir()
            cache = Path(td) / "index.json"
            cards = {
                "done.yml": {"id": "done", "action": {"status": "done"}},
                "queued.yml": {"id": "queued", "action": {"status": "queued"}},
                "running.yml": {"id": "running", "action": {"status": "running"}},
            }
            for name, card in cards.items():
                (root / name).write_text(yaml.safe_dump(card))

            original_load = self.mod.load_card
            with patch.object(self.mod, "load_card", wraps=original_load) as load:
                first = self.mod.load_dispatch_cards(root, cache)
                self.assertEqual(3, load.call_count)
                self.assertEqual({"queued", "running"},
                                 {card["id"] for _, card in first})

                load.reset_mock()
                second = self.mod.load_dispatch_cards(root, cache)
                self.assertEqual(2, load.call_count)
                self.assertEqual({"queued", "running"},
                                 {card["id"] for _, card in second})

                load.reset_mock()
                (root / "done.yml").write_text(
                    yaml.safe_dump({"id": "done", "action": {"status": "queued"}}))
                third = self.mod.load_dispatch_cards(root, cache)
                self.assertEqual(3, load.call_count)
                self.assertEqual({"done", "queued", "running"},
                                 {card["id"] for _, card in third})

    def test_malformed_cache_entry_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "cards"
            root.mkdir()
            cache = Path(td) / "index.json"
            card = {"id": "queued", "action": {"status": "queued"}}
            (root / "queued.yml").write_text(yaml.safe_dump(card))
            cache.write_text(
                f'{{"version":1,"root":"{root.resolve()}",'
                '"cards":{"queued.yml":"bad"}}')

            loaded = self.mod.load_dispatch_cards(root, cache)

            self.assertEqual("queued", loaded[0][1]["id"])
            self.assertIn('"status":"queued"', cache.read_text())

    def test_cache_is_scoped_to_card_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root_a = Path(td) / "a"
            root_b = Path(td) / "b"
            root_a.mkdir()
            root_b.mkdir()
            cache = Path(td) / "index.json"
            (root_a / "same.yml").write_text(
                yaml.safe_dump({"id": "a", "action": {"status": "done"}}))
            (root_b / "same.yml").write_text(
                yaml.safe_dump({"id": "b", "action": {"status": "queued"}}))

            self.mod.load_dispatch_cards(root_a, cache)
            loaded = self.mod.load_dispatch_cards(root_b, cache)

            self.assertEqual(["b"], [card["id"] for _, card in loaded])


if __name__ == "__main__":
    unittest.main()
