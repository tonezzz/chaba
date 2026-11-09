"""Unit test for lesson_primer — harvest + rank lesson lines from
jobs/cards/kb/outcome docs, matched on (host, repo, task keywords).
Also covers the positive (KNOWN_GOOD) channel: first-try-verified
cards + job-doc wins fields, plus the KANBAN_PRIMER_GOOD env gate
in kanban-dispatch build_task.

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
sys.path.insert(0, str(REPO / "scripts" / "board"))  # kanban-dispatch imports


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


def _mkroot_good(base: Path) -> Path:
    """Synthetic repo for the positive channel: first-try-verified
    cards, excluded cards, and a job doc with a wins field."""
    (base / "docs/ssot/jobs/lab").mkdir(parents=True)
    (base / "docs/ssot/kanban/cards").mkdir(parents=True)
    # eligible: verified, attempts 0, one substantive signal comm
    (base / "docs/ssot/kanban/cards/g-ok.yml").write_text(
        "id: g-ok\n"
        "spec: pre-warm the whisper primer bench on tony-omen\n"
        "action:\n  verified: true\n  attempts: 0\n"
        "comms:\n"
        "- at: 'x'\n  from: tony\n  text: 'queued for processing'\n"
        "- at: 'x'\n  from: chaba\n"
        "  text: 'auto-merged dispatch/2026-x → origin/master'\n"
        "- at: 'x'\n  from: devin\n"
        "  text: 'fixed in chaba: whisper primer pre-warm merged clean "
        "— the bench now runs warm on tony-omen'\n")
    # eligible: verified but comms carry no signal -> spec fallback
    (base / "docs/ssot/kanban/cards/g-fall.yml").write_text(
        "id: g-fall\n"
        "spec: keep the whisper bench summary line first\n"
        "action:\n  verified: true\n"
        "comms:\n"
        "- at: 'x'\n  from: devin\n  text: 'looking into the bench'\n")
    # excluded: needed retries
    (base / "docs/ssot/kanban/cards/g-retry.yml").write_text(
        "id: g-retry\n"
        "spec: whisper bench retry card\n"
        "action:\n  verified: true\n  attempts: 3\n"
        "comms:\n"
        "- at: 'x'\n  from: devin\n"
        "  text: 'whisper bench worked on the third try'\n")
    # excluded: not verified
    (base / "docs/ssot/kanban/cards/g-open.yml").write_text(
        "id: g-open\nspec: whisper bench unverified card\n"
        "action:\n  status: running\n"
        "comms:\n"
        "- at: 'x'\n  from: devin\n"
        "  text: 'whisper bench approach worked locally'\n")
    (base / "docs/ssot/jobs/lab/jwins.yml").write_text(
        "title: bench job\n"
        "report:\n"
        "  wins:\n"
        "    - whisper primer pre-warm on tony-omen worked — bench "
        "passes on the warm cache\n")
    return base


class GoodPrimerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    CARD = {"id": "voice-bench2", "title": "whisper bench rerun",
            "spec": "run the whisper bench on the gpu host",
            "action": {"repo": "ada-voice"}}

    def test_harvest_eligibility_and_content(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot_good(Path(td))
            cands = self.mod._positive_candidates(root)
            joined = "\n".join(t for t, _, _ in cands)
            self.assertIn("[g-ok] fixed in chaba: whisper primer pre-warm",
                          joined)
            # spec-summary fallback when no comms signal
            self.assertIn("[g-fall] keep the whisper bench summary line",
                          joined)
            # job-doc wins field
            self.assertIn("[jwins] whisper primer pre-warm", joined)
            # retry / unverified cards excluded
            self.assertNotIn("g-retry", joined)
            self.assertNotIn("g-open", joined)
            # noise comms never surface
            self.assertNotIn("auto-merged dispatch", joined)
            self.assertNotIn("queued for processing", joined)

    def test_build_good_scored_like_pitfalls(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot_good(Path(td))
            lines = self.mod.build_good(self.CARD, "tony-omen",
                                        "ada-voice", root)
            self.assertTrue(lines)
            self.assertLessEqual(len(lines), self.mod.GOOD_MAX_LINES)
            self.assertTrue(all(l.startswith("[") for l in lines))
            unrelated = {"id": "zz", "title": "qqq zzz", "spec": "xyzzy",
                         "action": {}}
            self.assertEqual(
                self.mod.build_good(unrelated, "other", "r", root), [])

    def test_format_good_block(self):
        block = self.mod.format_good_block(["[c] a", "[d] b"])
        self.assertIn(
            "KNOWN_GOOD — approaches that verified clean on similar "
            "work:", block)
        self.assertIn("- [c] a", block)
        self.assertNotIn("KNOWN_PITFALLS", block)


def _load_dispatch():
    spec = importlib.util.spec_from_file_location(
        "kanban_dispatch", REPO / "scripts/board/kanban-dispatch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BuildTaskGoodTest(unittest.TestCase):
    """build_task wires the good block after KNOWN_PITFALLS and honors
    KANBAN_PRIMER_GOOD=0 — lp.* stubbed so no real repo scan runs."""

    @classmethod
    def setUpClass(cls):
        cls.kd = _load_dispatch()

    def _env(self, **kv):
        saved = {k: os.environ.get(k) for k in kv}
        os.environ.update(kv)
        return saved

    def _restore(self, saved):
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_good_block_after_pitfalls(self):
        kd = self.kd
        saved = self._env(KANBAN_PRIMER="1", KANBAN_PRIMER_GOOD="1")
        try:
            old_b, old_g = kd.lp.build, kd.lp.build_good
            kd.lp.build = lambda *a: ["pit sentinel"]
            kd.lp.build_good = lambda *a: ["good sentinel"]
            try:
                task = kd.build_task({"id": "gx", "title": "t",
                                      "action": {"type": "dispatch"}})
            finally:
                kd.lp.build, kd.lp.build_good = old_b, old_g
        finally:
            self._restore(saved)
        self.assertIn("KNOWN_PITFALLS", task)
        self.assertIn("KNOWN_GOOD", task)
        self.assertLess(task.index("KNOWN_PITFALLS"),
                        task.index("KNOWN_GOOD"))
        self.assertIn("- good sentinel", task)

    def test_good_env_off(self):
        kd = self.kd
        saved = self._env(KANBAN_PRIMER="0", KANBAN_PRIMER_GOOD="0")
        try:
            old_g = kd.lp.build_good
            kd.lp.build_good = lambda *a: ["good sentinel"]
            try:
                task = kd.build_task({"id": "gy", "title": "t",
                                      "action": {"type": "dispatch"}})
            finally:
                kd.lp.build_good = old_g
        finally:
            self._restore(saved)
        self.assertNotIn("KNOWN_GOOD", task)
        self.assertNotIn("good sentinel", task)


if __name__ == "__main__":
    unittest.main()
