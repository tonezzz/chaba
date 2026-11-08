"""Unit tests for board-api /action do=archive (KNB-1178): eligibility
gate (done + action.verified + age) and the cards/archive/ file move.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import yaml

os.environ["BOARD_API_COMMIT"] = "0"

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "board_api", REPO / "scripts" / "board" / "board-api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card(column="done", verified=True, updated=None):
    return {
        "id": "test-card",
        "title": "t",
        "column": column,
        "updated": updated or (dt.datetime.now()
                               - dt.timedelta(days=10)).strftime(
                                   "%Y-%m-%d %H:%M"),
        "action": {"status": "done", "verified": verified},
        "comms": [],
    }


class DoArchiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_archives_verified_old_done(self):
        msg = self.mod.do_archive(_card(), "devin")
        self.assertIn("archived", msg)

    def test_rejects_unverified(self):
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(verified=False), "devin")

    def test_rejects_non_done_column(self):
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(column="review"), "devin")

    def test_rejects_fresh_card(self):
        fresh = (dt.datetime.now() - dt.timedelta(days=1)).strftime(
            "%Y-%m-%d %H:%M")
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(updated=fresh), "devin")

    def test_rejects_bad_timestamp(self):
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(updated="not-a-date"), "devin")


class ArchiveMoveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_move_writes_archive_copy_and_removes_source(self):
        with tempfile.TemporaryDirectory() as td:
            cards = Path(td) / "cards"
            cards.mkdir()
            src = cards / "test-card.yml"
            src.write_text(yaml.safe_dump(_card()))
            card = yaml.safe_load(src.read_text())
            self.mod.do_archive(card, "devin")  # handler order: gate, then move
            self.mod._archive_move(src, card)
            dest = cards / "archive" / "test-card.yml"
            self.assertFalse(src.exists())
            self.assertTrue(dest.exists())
            moved = yaml.safe_load(dest.read_text())
            self.assertEqual(moved["id"], "test-card")
            self.assertTrue(moved["comms"])  # archive comms line landed


if __name__ == "__main__":
    unittest.main()
