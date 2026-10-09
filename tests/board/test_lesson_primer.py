"""Unit test for lesson_primer — harvest + rank lesson lines from
jobs/cards/kb/outcome docs, matched on (host, repo, task keywords).

Runs against a synthetic repo root in tmp; no dispatch, no git.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/lesson_primer.py"


def _load():
    spec = importlib.util.spec_from_file_location("lesson_primer", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mkroot(base: Path) -> Path:
    (base / "docs/ssot/jobs/lab").mkdir(parents=True)
    (base / "docs/ssot/kanban/cards").mkdir(parents=True)
    (base / "docs/kb/ops").mkdir(parents=True)
    (base / "docs/ssot/jobs/lab/j1.yml").write_text(
        "title: voice bench\n"
        "method_notes: >\n"
        "  GOTCHA: whisper primer audio stalls when the model file is "
        "cold on tony-omen. Pre-warm before benching.\n"
        "side_findings: >\n"
        "  plain prose with no signal words at all.\n")
    (base / "docs/ssot/kanban/cards/c1.yml").write_text(
        "id: c1\ncomms:\n"
        "- at: 'x'\n  from: a\n"
        "  text: 'dispatch failed: whisper bench DEVIN_MODEL empty on "
        "tony-omen runner'\n"
        "- at: 'x'\n  from: a\n  text: 'all good'\n")
    (base / "docs/kb/ops/rb.md").write_text(
        "# Whisper bench runbook\n\nHow to pre-warm whisper models on "
        "tony-omen before a bench run.\n")
    (base / "dispatch-outcome-20261009-x.md").write_text(
        "# outcome\n\nlessons:\n"
        "- whisper bench never run two sessions on one GPU\n"
        "- second lesson line\n\n## verify\n")
    return base


class LessonPrimerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_harvests_all_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot(Path(td))
            card = {"id": "voice-bench", "title": "whisper bench rerun",
                    "spec": "run the whisper bench on the gpu host",
                    "action": {"repo": "ada-pi"}}
            lines = self.mod.build(card, "tony-omen", "ada-pi", root)
            joined = "\n".join(lines)
            self.assertIn("never run two sessions on one GPU", joined)
            self.assertIn("whisper primer audio stalls", joined)
            self.assertIn("[c1] dispatch failed", joined)
            self.assertIn("runbook docs/kb/ops/rb.md", joined)
            # prose without signal words is dropped
            self.assertNotIn("plain prose", joined)
            # unmatched comms are dropped
            self.assertNotIn("all good", joined)

    def test_no_match_no_lines(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot(Path(td))
            card = {"id": "zz", "title": "qqq unrelated zzz",
                    "spec": "xyzzy", "action": {}}
            self.assertEqual(
                self.mod.build(card, "other-host", "otherrepo", root), [])

    def test_format_block(self):
        block = self.mod.format_block(["l1", "l2"], "h", "r")
        self.assertIn("KNOWN_PITFALLS", block)
        self.assertIn("- l1", block)
        self.assertIn("host=h", block)


if __name__ == "__main__":
    unittest.main()
