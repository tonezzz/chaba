"""Unit test for lesson_qc — advisory QC over the lesson corpus:
duplicate clustering, staleness flags, contradiction candidates,
health counts, output/state idempotency.

Runs against a synthetic repo root in tmp; no dispatch, no git.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/lesson_qc.py"


def _load():
    spec = importlib.util.spec_from_file_location("lesson_qc", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mkroot(base: Path) -> Path:
    (base / "docs/ssot/jobs/lab").mkdir(parents=True)
    (base / "docs/ssot/kanban/cards").mkdir(parents=True)
    (base / "scripts/board").mkdir(parents=True)
    (base / "scripts/board/exists.py").write_text("# exists\n")
    (base / "docs/ssot/jobs/lab/j1.yml").write_text(
        "title: t\n"
        "method_notes: >\n"
        "  GOTCHA: never run two sessions on one GPU — the whisper bench "
        "stalls. Always pre-warm the whisper model before benching.\n")
    (base / "docs/ssot/kanban/cards/c1.yml").write_text(
        "id: c1\ncomms:\n"
        "- at: 'x'\n  from: a\n"
        "  text: 'lesson: never run two sessions on one gpu, dispatch "
        "failed on tony-omen'\n"
        "- at: 'x'\n  from: a\n"
        "  text: 'lesson: mddb on idc01 must be seeded before queries'\n"
        "- at: 'x'\n  from: a\n"
        "  text: 'failed: scripts/board/deleted_thing.py is gone now'\n"
        "- at: 'x'\n  from: a\n"
        "  text: 'failed: scripts/board/exists.py is still there'\n"
        "- at: 'x'\n  from: a\n"
        "  text: 'gotcha: ~/CascadeProjects/old-repo/scripts/x.py moved'\n"
        "- at: 'x'\n  from: a\n"
        "  text: 'lesson: always pre-warm the whisper model file before "
        "any bench run'\n"
        "- a bare string comm that must not crash harvest\n")
    (base / "docs/ssot/kanban/cards/c2.yml").write_text(
        "id: c2\ncomms:\n"
        "- at: 'x'\n  from: a\n"
        "  text: 'lesson: always pre-warm the whisper model file before "
        "any bench run'\n")
    (base / "docs/ssot/kanban/cards/c3.yml").write_text(
        "id: c3\naction:\n  type: dispatch\n  repo: ada-voice\ncomms:\n"
        "- at: 'x'\n  from: a\n"
        "  text: 'failed: scripts/board/deleted_thing.py missing in "
        "ada-voice too'\n")
    (base / "dispatch-outcome-20261101-a.md").write_text(
        "# outcome\n\nlessons:\n"
        "- never run two sessions on one gpu\n"
        "- plain line without signal\n\n## verify\n")
    (base / "dispatch-outcome-20261101-b.md").write_text(
        "# outcome\n\nno lessons block at all\n")
    return base


class LessonQcTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def _harvest(self, base):
        recs, meta = self.mod.harvest(base)
        return recs, meta

    def test_harvest_all_sources_and_str_comm(self):
        with tempfile.TemporaryDirectory() as td:
            recs, meta = self._harvest(_mkroot(Path(td)))
            kinds = {r["kind"] for r in recs}
            self.assertEqual(kinds, {"outcome", "job", "comms"})
            self.assertEqual(meta["outcome"]["docs"], 2)
            self.assertEqual(meta["outcome"]["docs_with_lessons"], 1)
            self.assertEqual(meta["outcome"]["lines"], 2)
            # bare-string comm tolerated, signal comms harvested
            self.assertTrue(any("idc01" in r["text"] for r in recs))

    def test_dup_clusters(self):
        with tempfile.TemporaryDirectory() as td:
            recs, _ = self._harvest(_mkroot(Path(td)))
            clusters = self.mod.dup_clusters(recs)
            joined = " | ".join(c["representative"] for c in clusters)
            self.assertIn("always pre-warm the whisper model file",
                          joined.lower())
            warm = [c for c in clusters
                    if "pre-warm the whisper model file"
                    in c["representative"].lower()]
            self.assertTrue(warm and warm[0]["count"] >= 2)

    def test_stale_flags(self):
        with tempfile.TemporaryDirectory() as td:
            base = _mkroot(Path(td))
            recs, _ = self._harvest(base)
            flags = self.mod.stale_flags(recs, base)
            hits = {h for f in flags for h in f["hits"]}
            self.assertIn("retired-ref:idc01", hits)
            self.assertIn("missing-path:scripts/board/deleted_thing.py",
                          hits)
            self.assertIn("renamed-repo:old-repo", hits)
            self.assertNotIn("missing-path:scripts/board/exists.py",
                             hits)
            # card declared for ada-voice: its missing path is not
            # checkable against this repo — no missing-path hit on it
            ada = [f for f in flags if "ada-voice too" in f["text"]]
            self.assertFalse(any(h.startswith("missing-path")
                                 for f in ada for h in f["hits"]))

    def test_contradiction_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            recs = [
                {"text": "never rotate the fleet database encryption "
                         "key mid-bench",
                 "src": "a", "kind": "comms"},
                {"text": "always rotate the fleet database encryption "
                         "key mid-bench",
                 "src": "b", "kind": "comms"},
            ]
            pairs = self.mod.contradiction_candidates(recs)
            self.assertTrue(any(
                "fleet" in p["signature"] and "database" in p["signature"]
                for p in pairs))

    def test_main_writes_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            base = _mkroot(Path(td))
            state = base / "state.json"
            argv = ["lesson_qc.py", "--root", str(base),
                    "--state", str(state), "--no-ops-event",
                    "--date", "2026-11-09"]
            old = sys.argv
            try:
                sys.argv = argv
                self.assertEqual(self.mod.main(), 0)
            finally:
                sys.argv = old
            job = base / "docs/ssot/jobs/kanban/2026-11-09-lesson-qc.yml"
            rep = base / "reports/lesson-qc-2026-11-09.md"
            self.assertTrue(job.exists() and rep.exists())
            self.assertIn("retired-ref", rep.read_text())
            st = json.loads(state.read_text())
            self.assertGreater(st["corpus"]["total_lines"], 0)
            # run twice more: convergent idempotency — once the growth
            # delta settles at 0 the artifacts are byte-identical
            prev = None
            for _ in range(2):
                try:
                    sys.argv = argv
                    self.assertEqual(self.mod.main(), 0)
                finally:
                    sys.argv = old
                cur = (job.read_text(), rep.read_text())
                if prev is not None:
                    self.assertEqual(prev, cur)
                prev = cur
            st2 = json.loads(state.read_text())
            self.assertEqual(st2["corpus"]["total_lines"],
                             st["corpus"]["total_lines"])


if __name__ == "__main__":
    unittest.main()
