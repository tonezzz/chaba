"""Fault-injection tests for card_io atomic writes + FileSink flush.

2026-11-19 idc03 ENOSPC incident (card kanban-card-torn-write-
investigation-b4034e): merge-sweep's locked_edit fallback did a direct
write_text on docs/ssot/kanban/cards/*.yml and tore three cards
mid-scalar when the disk filled. card_io.atomic_write_text must leave
either the old or the new COMPLETE file — never a torn one — no matter
where the failure lands, and must not leak *.tmp shells.

Covers: failure during fsync (ENOSPC), failure at os.replace (kill
mid-write), success leaves new content + no tmp, atomic_dump_card's
refuse-before-touch round-trip guard, and FileSink.flush going through
the atomic path under the board flock.
"""

from __future__ import annotations

import errno
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))
import card_io  # noqa: E402


def _no_tmps(d: Path) -> list[Path]:
    return [p for p in d.iterdir() if p.name.endswith(".tmp")]


class AtomicWriteTextTest(unittest.TestCase):

    def test_success_writes_complete_new_content(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.yml"
            p.write_text("id: c\ncolumn: backlog\n")
            card_io.atomic_write_text(p, "id: c\ncolumn: done\n")
            self.assertEqual(p.read_text(), "id: c\ncolumn: done\n")
            self.assertEqual(_no_tmps(Path(td)), [])

    def test_enospc_at_fsync_leaves_original_byte_identical(self):
        """Disk full surfacing at fsync: target untouched, tmp removed."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.yml"
            original = "id: c\ncolumn: backlog\nnote: keep me\n"
            p.write_text(original)

            def boom(fd):
                raise OSError(errno.ENOSPC, "No space left on device")

            with mock.patch.object(card_io.os, "fsync", side_effect=boom):
                with self.assertRaises(OSError):
                    card_io.atomic_write_text(p, "id: c\ncolumn: done\n")
            self.assertEqual(p.read_text(), original)
            self.assertEqual(_no_tmps(Path(td)), [])

    def test_kill_before_rename_leaves_original_byte_identical(self):
        """os.replace never completing (kill/ENOSPC at rename): old file
        stays whole — the torn tmp never reaches the real path."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.yml"
            original = "id: c\ncolumn: backlog\n"
            p.write_text(original)
            with mock.patch.object(
                    card_io.os, "replace",
                    side_effect=OSError(errno.ENOSPC, "disk full")):
                with self.assertRaises(OSError):
                    card_io.atomic_write_text(p, "id: c\ncolumn: done\n")
            self.assertEqual(p.read_text(), original)
            self.assertEqual(_no_tmps(Path(td)), [])

    def test_replace_is_the_only_observable_transition(self):
        """Readers see old or new — prove the file object itself is
        swapped via rename, not rewritten in place."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.yml"
            p.write_text("id: c\ncolumn: backlog\n")
            ino_before = p.stat().st_ino
            card_io.atomic_write_text(p, "id: c\ncolumn: done\n")
            self.assertNotEqual(p.stat().st_ino, ino_before)
            self.assertEqual(yaml.safe_load(p.read_text())["column"],
                             "done")


class AtomicDumpCardTest(unittest.TestCase):

    def test_dump_round_trips_and_is_complete(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.yml"
            card = {"id": "c", "column": "doing",
                    "comms": [{"at": "2026-11-19 11:00", "from": "devin",
                               "text": "x" * 5000}]}
            card_io.atomic_dump_card(p, card)
            self.assertEqual(yaml.safe_load(p.read_text()), card)

    def test_refuse_before_touch_on_non_mapping_dump(self):
        """A serialization that won't re-parse as a card mapping is
        refused BEFORE the file is touched (board-api.save contract)."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.yml"
            original = "id: c\ncolumn: backlog\n"
            p.write_text(original)
            with self.assertRaises(ValueError):
                card_io.atomic_dump_card(p, ["not", "a", "mapping"])
            self.assertEqual(p.read_text(), original)
            self.assertEqual(_no_tmps(Path(td)), [])


class FileSinkAtomicTest(unittest.TestCase):
    """scripts/ci/card-pipeline.py FileSink — the last direct write_text
    on card YAML found in the 2026-11-19 audit. flush() must go through
    card_io so a mid-flush fault leaves the card whole."""

    @classmethod
    def setUpClass(cls):
        cls._lockdir = tempfile.TemporaryDirectory()
        os.environ["BOARD_LOCK"] = str(
            Path(cls._lockdir.name) / "board.lock")
        spec = importlib.util.spec_from_file_location(
            "card_pipeline", REPO / "scripts" / "ci" / "card-pipeline.py")
        cls.cp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cp)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("BOARD_LOCK", None)
        cls._lockdir.cleanup()

    def test_flush_failure_leaves_card_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            cd = Path(td)
            original = yaml.safe_dump({"id": "c", "column": "backlog"})
            (cd / "c.yml").write_text(original)
            fs = self.cp.FileSink(cd, render=False, dry_run=False)
            fs.comment("c", "pipeline note")
            with mock.patch.object(
                    card_io.os, "replace",
                    side_effect=OSError(errno.ENOSPC, "disk full")):
                with self.assertRaises(OSError):
                    fs.flush()
            self.assertEqual((cd / "c.yml").read_text(), original)
            self.assertEqual(_no_tmps(cd), [])

    def test_flush_success_writes_complete_card(self):
        with tempfile.TemporaryDirectory() as td:
            cd = Path(td)
            (cd / "c.yml").write_text(
                yaml.safe_dump({"id": "c", "column": "backlog"}))
            fs = self.cp.FileSink(cd, render=False, dry_run=False)
            fs.comment("c", "pipeline note")
            fs.flush()
            saved = yaml.safe_load((cd / "c.yml").read_text())
            self.assertEqual(saved["id"], "c")
            self.assertEqual(saved["comms"][0]["text"], "pipeline note")
            self.assertEqual(_no_tmps(cd), [])


if __name__ == "__main__":
    unittest.main()
