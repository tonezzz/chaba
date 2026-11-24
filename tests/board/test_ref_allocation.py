"""Regression: explicit card refs must reserve their number in .ref-seq
(OPS-1037 collision — an explicit OPS-1037 never advanced the counter,
so a later auto-allocated card was minted with the same ref).
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "board_api_ref_allocation",
        REPO / "scripts" / "board" / "board-api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RefAllocationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cards = Path(self.tmp.name) / "cards"
        self.cards.mkdir()
        self._old_card_dir = self.mod.CARD_DIR
        self.mod.CARD_DIR = self.cards
        self.commit_patch = patch.dict("os.environ", {"BOARD_API_COMMIT": "0"})
        self.commit_patch.start()
        self.addCleanup(self.commit_patch.stop)
        self.addCleanup(setattr, self.mod, "CARD_DIR", self._old_card_dir)

    def seq(self) -> int:
        p = self.cards / ".ref-seq"
        return int(p.read_text().strip() or 0) if p.exists() else 0

    def test_explicit_ref_reserves_number_for_next_auto_ref(self):
        first = self.mod.do_create(
            {"id": "first", "title": "first",
             "ref": "OPS-1037"}, "tony")
        self.assertEqual(first["ref"], "OPS-1037")
        self.assertEqual(self.seq(), 1037)

        second = self.mod.do_create(
            {"id": "second", "title": "second"}, "tony")
        self.assertEqual(second["ref"], "OPS-1038")
        self.assertEqual(self.seq(), 1038)

    def test_explicit_ref_never_lowers_counter(self):
        self.mod.do_create({"id": "high", "title": "high",
                            "ref": "ADA-9000"}, "tony")
        self.assertEqual(self.seq(), 9000)
        self.mod.do_create({"id": "low", "title": "low",
                            "ref": "OPS-0042"}, "tony")
        self.assertEqual(self.seq(), 9000)
        third = self.mod.do_create({"id": "third", "title": "third"}, "tony")
        self.assertEqual(third["ref"], "OPS-9001")

    def test_explicit_ref_without_seq_scans_existing_cards(self):
        # no .ref-seq yet: seed from the board's cards, then take the
        # higher of the seed and the explicit ref
        (self.cards / "old.yml").write_text(
            "id: old\ntitle: old\nref: OPS-0500\n")
        self.mod.do_create({"id": "new", "title": "new",
                            "ref": "OPS-0600"}, "tony")
        self.assertEqual(self.seq(), 600)
        nxt = self.mod.do_create({"id": "next", "title": "next"}, "tony")
        self.assertEqual(nxt["ref"], "OPS-0601")


if __name__ == "__main__":
    unittest.main()
