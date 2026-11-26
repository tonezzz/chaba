"""Regression: card YAML write paths must persist date scalars as strings.

2026-11-09 board-api /cards 502 outage (card
board-api-date-serialization-outage): card YAMLs carrying bare
``created: 2026-11-09`` scalars load via PyYAML as datetime.date, and
every plain ``json.dumps(card)`` consumer died with TypeError — Ada's
status tools were down fleet-wide. The reader side was fixed by
``json.dumps(..., default=str)`` (ca8d850275); this suite pins the
write-side hygiene: both card write doors — ``card_io.atomic_dump_card``
and ``board-api.save`` — normalize date/datetime objects to ISO strings
before dumping, so the persisted YAML quotes them and re-parses as str.

Each test writes a card the way production does (a YAML file with bare
date scalars -> yaml.safe_load -> mutate -> write door -> reload) and
asserts the persisted fields are strings that survive json.dumps.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

os.environ["BOARD_API_COMMIT"] = "0"  # tmp dirs aren't repo files

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import card_io  # noqa: E402


def _load_board_api():
    spec = importlib.util.spec_from_file_location(
        "board_api", REPO / "scripts" / "board" / "board-api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A card as it exists on disk today: bare date-only `created:` plus a
# bare `updated:` — both resolve to date/datetime objects on load.
ON_DISK = """\
id: c
column: backlog
title: date scalar card
created: 2026-11-09
updated: 2026-11-26
comms:
- at: 2026-11-20
  from: devin
  text: hello
"""


def _assert_json_safe(testcase, saved: dict) -> None:
    """The persisted card must re-parse with str date fields and
    survive a plain json.dumps — the exact consumer shape that 502'd."""
    testcase.assertIsInstance(saved["created"], str)
    testcase.assertIsInstance(saved["updated"], str)
    testcase.assertIsInstance(saved["comms"][0]["at"], str)
    testcase.assertEqual(saved["created"], "2026-11-09")
    json.dumps(saved)  # must not raise TypeError


class AtomicDumpCardDateTest(unittest.TestCase):
    """card_io.atomic_dump_card — the shared write door used by
    merge-sweep, kanban-commit, answer-sweep, request-sweep,
    runner-fleet-health, deploy-preflight, board-render-guard,
    reconcile-local-conflicts, ref-backfill, lab-review-sweep,
    review-digest, audit-hosts, card-pipeline FileSink, kanban-act
    callers, and the ada/* health watchers."""

    def test_bare_dates_persist_as_strings(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.yml"
            p.write_text(ON_DISK)
            card = yaml.safe_load(p.read_text())
            # sanity: the hazard is real — PyYAML made these date objs
            self.assertIsInstance(card["created"], dt.date)
            self.assertIsInstance(card["updated"], dt.date)

            card["note"] = "mutated"
            card_io.atomic_dump_card(p, card)

            saved = yaml.safe_load(p.read_text())
            _assert_json_safe(self, saved)
            # and the on-disk scalars are quoted, not bare
            text = p.read_text()
            self.assertIn("created: '2026-11-09'", text)

    def test_nested_datetime_objects_normalize(self):
        """datetime.datetime anywhere in the structure (nested maps,
        lists) becomes an ISO string too."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.yml"
            stamp = dt.datetime(2026, 11, 26, 20, 55, 33,
                                tzinfo=dt.timezone.utc)
            card = {"id": "c", "column": "backlog",
                    "action": {"started": stamp},
                    "requests": [{"at": stamp, "ask": "?"}],
                    "tags": ("a", "b")}
            card_io.atomic_dump_card(p, card)
            saved = yaml.safe_load(p.read_text())
            self.assertIsInstance(saved["action"]["started"], str)
            self.assertIsInstance(saved["requests"][0]["at"], str)
            self.assertEqual(saved["tags"], ["a", "b"])
            json.dumps(saved)


class BoardApiSaveDateTest(unittest.TestCase):
    """board-api.save — the HTTP write door behind /card /comment
    /action /move /respond etc."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_board_api()

    def test_save_persists_dates_as_strings(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.yml"
            p.write_text(ON_DISK)
            card = yaml.safe_load(p.read_text())
            card["updated"] = self.mod.now()
            self.mod.save(p, card)

            saved = yaml.safe_load(p.read_text())
            _assert_json_safe(self, saved)


if __name__ == "__main__":
    unittest.main()
