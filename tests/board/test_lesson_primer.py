"""Unit test for lesson_primer — harvest + rank lesson lines from
jobs/cards/kb/outcome docs, matched on (host, repo, task keywords).

Covers: word-boundary keyword scoring, task-keyword eligibility
(host/repo tokens rank but cannot qualify), stale-source demotion, and
the retired-infra filter with its 2-task-keyword escape.

Runs against a synthetic repo root in tmp; no dispatch, no git.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
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
                    "action": {"repo": "ada-voice"}}
            lines = self.mod.build(card, "tony-omen", "ada-voice", root)
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

    def test_substring_keywords_do_not_match(self):
        # word boundaries: 'test' ∉ 'latest'/'protest', 'card' ∉ 'discard'
        self.assertEqual(
            self.mod._score("latest protest discard", {"test", "card"}), 0)
        self.assertEqual(
            self.mod._score("test the card again", {"test", "card"}), 2)
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot(Path(td))
            (root / "docs/ssot/jobs/lab/j2.yml").write_text(
                "gotchas: |\n"
                "  GOTCHA: latest protest discard on bench run\n")
            card = {"id": "tb", "title": "test bench",
                    "spec": "test bench", "action": {}}
            # old substring scoring: test∈latest + card∈discard + bench = 3;
            # word-boundary scoring: bench only = 1 < MIN_SCORE → dropped
            self.assertNotIn(
                "latest protest discard",
                "\n".join(self.mod.build(card, "hx", "rx", root)))

    def test_host_only_line_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot(Path(td))
            (root / "docs/ssot/jobs/lab/j2.yml").write_text(
                "gotchas: |\n"
                "  GOTCHA: tony-omen ada-voice deploy failed often\n"
                "  GOTCHA: whisper fails on tony-omen during cold starts\n")
            card = {"id": "wb", "title": "whisper bench",
                    "spec": "whisper bench", "action": {}}
            joined = "\n".join(
                self.mod.build(card, "tony-omen", "ada-voice", root))
            # host+repo only (score 2 but zero task kws) → cannot qualify
            self.assertNotIn("deploy failed often", joined)
            # task kw + host kw → accepted
            self.assertIn("whisper fails on tony-omen", joined)

    def test_stale_source_demoted(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot(Path(td))
            stale = root / "docs/ssot/jobs/lab/old.yml"
            stale.write_text(
                "gotchas: |\n"
                "  GOTCHA: whisper stalls on tony-omen when cache is cold\n"
                "  GOTCHA: whisper bench fails on tony-omen without "
                "pre-warm\n")
            old = time.time() - (self.mod.STALE_DAYS + 10) * 86400
            os.utime(stale, (old, old))
            card = {"id": "wb", "title": "whisper bench",
                    "spec": "whisper bench", "action": {}}
            joined = "\n".join(
                self.mod.build(card, "tony-omen", "ada-voice", root))
            # score 2 stale → 2-1=1 < MIN_SCORE → dropped
            self.assertNotIn("cache is cold", joined)
            # score 3 stale → 3-1=2 → survives the demotion
            self.assertIn("without pre-warm", joined)

    def test_retired_host_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot(Path(td))
            (root / "docs/ssot/jobs/lab/j2.yml").write_text(
                "gotchas: |\n"
                "  GOTCHA: idc01 whisper outage broke tony-omen "
                "ada-voice deploys\n"
                "  GOTCHA: idc01 whisper bench crashed during sync\n")
            card = {"id": "wb", "title": "whisper bench",
                    "spec": "whisper bench", "action": {}}
            joined = "\n".join(
                self.mod.build(card, "tony-omen", "ada-voice", root))
            # retired host + only 1 task hit → dropped despite score 3
            self.assertNotIn("outage broke", joined)
            # >=2 task hits → survives the retired-infra filter
            self.assertIn("crashed during sync", joined)


if __name__ == "__main__":
    unittest.main()
