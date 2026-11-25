"""Unit tests for board-api /action do=archive (KNB-1178): eligibility
gate (done + action.verified + age) and the cards/archive/ file move.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_min_days_override_lets_recovery_pass_age_fresh_stamps(self):
        fresh = (dt.datetime.now() - dt.timedelta(days=1)).strftime(
            "%Y-%m-%d %H:%M")
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(updated=fresh), "devin")
        self.assertIn("archived", self.mod.do_archive(
            _card(updated=fresh), "devin", min_days=0))

    def test_min_days_override_keeps_verified_and_column_gates(self):
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(verified=False), "devin", min_days=0)
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(column="review"), "devin", min_days=0)

    def test_date_only_updated_parses(self):
        # auto-generated cards (runner-auto-*, disk-auto-*, cms-auto-*)
        # stamp updated date-only '%Y-%m-%d' — the door must not reject
        # them as unparseable or they can never archive (KNB-1178)
        old = (dt.datetime.now() - dt.timedelta(days=30)).strftime(
            "%Y-%m-%d")
        self.assertIn("archived", self.mod.do_archive(
            _card(updated=old), "devin"))
        fresh = dt.datetime.now().strftime("%Y-%m-%d")
        with self.assertRaises(ValueError):
            self.mod.do_archive(_card(updated=fresh), "devin")


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

    def test_date_only_updated_is_a_candidate(self):
        # auto-card date-only stamps must not be invisible to the sweep
        with tempfile.TemporaryDirectory() as td:
            old = (dt.datetime.now() - dt.timedelta(days=30)).strftime(
                "%Y-%m-%d")
            c = _card(updated=old)
            c["id"] = "auto-old"
            Path(td, "auto-old.yml").write_text(yaml.safe_dump(c))
            mod = self._sweep(td)
            try:
                total, verified, capped = mod.plan(7.0, 600)
            finally:
                os.environ.pop("KANBAN_CARD_DIR", None)
            self.assertEqual(total, 1)
            self.assertEqual([c["id"] for c in verified], ["auto-old"])

    def test_request_carries_days_to_the_write_door(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["KANBAN_CARD_DIR"] = td
            mod = self._sweep(td)
            try:
                with mock.patch.object(mod.urllib.request, "urlopen") as op:
                    reply = mock.MagicMock()
                    reply.__enter__.return_value.read.return_value = b"{}"
                    op.return_value = reply
                    mod.archive("v1", False, days=2.0)
                    req = op.call_args[0][0]
                    body = json.loads(req.data)
            finally:
                os.environ.pop("KANBAN_CARD_DIR", None)
            self.assertEqual(body["min_days"], 2.0)
            self.assertEqual(body["do"], "archive")
            self.assertNotIn("cap", body)


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
