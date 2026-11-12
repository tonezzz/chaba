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

    def test_cap_archives_unverified_old_done(self):
        card = _card(verified=False)
        msg = self.mod.do_archive(card, "devin", cap=True)
        self.assertIn("archived", msg)
        self.assertIn("card cap", card["comms"][-1]["text"])

    def test_cap_still_rejects_non_done_and_fresh(self):
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(column="backlog", verified=False),
                                "devin", cap=True)
        fresh = (dt.datetime.now() - dt.timedelta(days=1)).strftime(
            "%Y-%m-%d %H:%M")
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(verified=False, updated=fresh),
                                "devin", cap=True)

    def test_cap_skips_unanswered_request(self):
        card = _card(verified=False)
        card["requests"] = [{"id": "r1", "ask": "?"}]
        with self.assertRaises(ValueError):
            self.mod.do_archive(card, "devin", cap=True)


class SweepPlanTest(unittest.TestCase):
    """archive-done.py plan(): verified first, then oldest done to cap."""

    def _sweep(self, td):
        os.environ["KANBAN_CARD_DIR"] = td
        spec = importlib.util.spec_from_file_location(
            "archive_done", REPO / "scripts" / "board" / "archive-done.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_cap_takes_oldest_unverified_done_only(self):
        with tempfile.TemporaryDirectory() as td:
            def put(cid, **kw):
                c = _card(**kw)
                c["id"] = cid
                Path(td, f"{cid}.yml").write_text(yaml.safe_dump(c))
            old = lambda d: (dt.datetime.now() - dt.timedelta(days=d)
                             ).strftime("%Y-%m-%d %H:%M")
            put("v1", verified=True)
            put("u-old", verified=False, updated=old(40))
            put("u-mid", verified=False, updated=old(20))
            put("u-fresh", verified=False, updated=old(1))
            put("live", column="backlog", verified=False)
            mod = self._sweep(td)
            try:
                total, verified, capped = mod.plan(7.0, 2)
            finally:
                os.environ.pop("KANBAN_CARD_DIR", None)
            self.assertEqual(total, 5)
            self.assertEqual([c["id"] for c in verified], ["v1"])
            self.assertEqual([c["id"] for c in capped], ["u-old", "u-mid"])


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


class UnarchiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_unarchive_restores_to_cards_dir(self):
        with tempfile.TemporaryDirectory() as td:
            cards = Path(td) / "cards"
            adir = cards / "archive"
            adir.mkdir(parents=True)
            src = adir / "test-card.yml"
            src.write_text(yaml.safe_dump(_card()))
            card = yaml.safe_load(src.read_text())
            self.mod.do_unarchive(card, "devin")
            self.mod._unarchive_move(src, card)
            dest = cards / "test-card.yml"
            self.assertFalse(src.exists())
            self.assertTrue(dest.exists())
            moved = yaml.safe_load(dest.read_text())
            self.assertTrue(moved["comms"])

    def test_do_unarchive_rejects_wrong_column(self):
        with self.assertRaises(ValueError):
            self.mod.do_unarchive(_card(column="review"), "devin")


if __name__ == "__main__":
    unittest.main()
