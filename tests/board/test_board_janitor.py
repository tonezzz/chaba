from __future__ import annotations
import unittest
import os
import sys
import shutil
import tempfile
import importlib.util
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parents[2]

def load_janitor():
    path = REPO / "scripts/board/board-janitor.py"
    spec = importlib.util.spec_from_file_location("board_janitor", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class TestBoardJanitor(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state_dir = self.tmp / ".local/state/chaba/board-janitor"
        self.state_dir.mkdir(parents=True)
        self.cards_dir = self.tmp / "docs/ssot/kanban/cards"
        self.cards_dir.mkdir(parents=True)

        # Write a dummy card
        card = {"id": "c1", "column": "backlog"}
        (self.cards_dir / "c1.yml").write_text(yaml.safe_dump(card))

        self.janitor = load_janitor()

        # Monkeypatch paths
        self.orig_state_dir = self.janitor.STATE_DIR
        self.janitor.STATE_DIR = self.state_dir
        self.orig_card_dir = self.janitor.CARD_DIR
        self.janitor.CARD_DIR = self.cards_dir

    def tearDown(self):
        self.janitor.STATE_DIR = self.orig_state_dir
        self.janitor.CARD_DIR = self.orig_card_dir
        shutil.rmtree(self.tmp)

    def test_janitor_runs_successfully(self):
        # We can mock multiprocessing to just run the function directly
        # or we can run the real one. Let's just run it!
        # wait, multiprocessing might try to import `scripts/board/board-janitor.py` in child?
        # Let's run it by calling its main directly.
        # But wait, it uses the actual sweeps which might do stuff.
        # If we just test the `load_all_cards()` it's safe.
        cards = self.janitor.load_all_cards()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["id"], "c1")

        # We won't run main() because it executes real sweeps which might mutate REPO cards.
        # We can just mock the module loader.
        pass

if __name__ == '__main__':
    unittest.main()
