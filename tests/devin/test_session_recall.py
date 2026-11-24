"""Unit tests for the hybrid T1/T2 session recall path
(card distiller-enrich-productionize).

Covers the contracts that don't need mddb or a live sessions.db:
session_recall.py FTS5 query building, chunking, BM25 retrieval, and
incremental indexing; sync-devin-summaries.py's sticky "## Artifacts"
preservation (enrichment must be a ratchet — post-delete and non-enrich
syncs never strip the section).
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("session_recall", REPO / "scripts/devin/session/session_recall.py")
sds = _load("sync_devin_summaries",
            REPO / "scripts/ada/sync-devin-summaries.py")


class FtsQueryTest(unittest.TestCase):
    def test_terms_quoted_or(self):
        q = sr.fts_query("kanban dispatch merge OPS-1234")
        self.assertIn('"kanban"', q)
        self.assertIn('"dispatch"', q)
        self.assertIn('"merge"', q)
        self.assertIn('"ops-1234"', q)
        self.assertIn(" OR ", q)

    def test_stopwords_dropped(self):
        q = sr.fts_query("what is the status of the card")
        self.assertNotIn('"the"', q)
        self.assertNotIn('"what"', q)
        self.assertIn('"status"', q)
        self.assertIn('"card"', q)

    def test_empty_when_nothing_usable(self):
        self.assertEqual(sr.fts_query("the and for"), "")
        self.assertEqual(sr.fts_query(""), "")

    def test_term_cap(self):
        q = sr.fts_query(" ".join(f"term{i}" for i in range(30)))
        self.assertEqual(q.count('"'), 2 * sr.T2_TERMS)


class ChunkingTest(unittest.TestCase):
    def test_overlap(self):
        text = "x" * (sr.CHUNK * 2)
        chunks = list(sr._chunks(text))
        self.assertEqual(len(chunks), 3)
        # second chunk restarts CHUNK-OVERLAP chars before the first ends
        self.assertTrue(chunks[1].startswith(text[sr.CHUNK - sr.CHUNK_OVERLAP:]
                                             [:20]))


class RecallT2Test(unittest.TestCase):
    def _con(self):
        con = sqlite3.connect(":memory:")
        con.execute(
            "CREATE TABLE files(path TEXT PRIMARY KEY, mtime REAL, "
            "size INTEGER)")
        con.execute(
            "CREATE VIRTUAL TABLE chunks USING fts5("
            "session UNINDEXED, path UNINDEXED, text, "
            "tokenize='porter unicode61')")
        return con

    def test_bm25_finds_right_session(self):
        con = self._con()
        docs = {
            "alpha": "the deploy failed with err canon-frobnicate-42 "
                     + "filler " * 200,
            "beta": "unrelated lunch menu discussion " + "filler " * 200,
        }
        for sess, text in docs.items():
            for c in sr._chunks(text):
                con.execute(
                    "INSERT INTO chunks(session, path, text) "
                    "VALUES (?,?,?)", (sess, f"/x/{sess}.md", c))
        hits = sr.recall_t2(con, "canon frobnicate deploy error")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["session"], "alpha")
        self.assertIn("canon", hits[0]["snippet"])

    def test_no_match_empty(self):
        con = self._con()
        con.execute("INSERT INTO chunks(session, path, text) "
                    "VALUES ('s','/x/s.md','hello world')")
        self.assertEqual(sr.recall_t2(con, "zyzzyva quux"), [])


class IndexArchivesTest(unittest.TestCase):
    def test_incremental_and_stale_removal(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.md").write_text("alpha session about frobnicate")
            old_idx = Path(td) / "idx"
            old_dirs = sr.ARCHIVE_DIRS
            old_db = sr.INDEX_DB
            try:
                sr.ARCHIVE_DIRS = [d]
                sr.INDEX_DB = old_idx
                con = sr.open_index()
                st = sr.index_archives(con, budget=60)
                self.assertEqual(st["indexed"], 1)
                # second run: nothing changed -> fresh, not re-indexed
                st = sr.index_archives(con, budget=60)
                self.assertEqual(st["indexed"], 0)
                self.assertEqual(st["fresh"], 1)
                # file removed -> its chunks go too
                (d / "a.md").unlink()
                st = sr.index_archives(con, budget=60)
                self.assertEqual(st["removed"], 1)
                self.assertEqual(sr.recall_t2(con, "frobnicate"), [])
            finally:
                sr.ARCHIVE_DIRS = old_dirs
                sr.INDEX_DB = old_db


class MainFailOpenTest(unittest.TestCase):
    """A dead T2 index must not take the T1 semantic lane down with it —
    and vice versa. The hook depends on each lane degrading alone."""

    def test_t1_survives_t2_index_failure(self):
        fake_t1 = [{"key": "devin-session/aluminum-opossum",
                    "score": 0.71, "content": "VCAST stale socket fix"}]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sr, "open_index",
                               side_effect=sqlite3.OperationalError(
                                   "no such module: fts5")), \
             mock.patch.object(sr, "recall_t1", return_value=fake_t1), \
             mock.patch.object(sr, "recall_t2", return_value=[]), \
             mock.patch.object(sys, "argv",
                               ["session_recall.py", "vcast idle stream"]), \
             contextlib.redirect_stdout(out), \
             contextlib.redirect_stderr(err):
            rc = sr.main()
        self.assertEqual(rc, 0)
        self.assertIn("devin-session/aluminum-opossum", out.getvalue())
        self.assertIn("t2 index unavailable", err.getvalue())

    def test_empty_lanes_emit_nothing(self):
        out = io.StringIO()
        with mock.patch.object(sr, "open_index",
                               return_value=sqlite3.connect(":memory:")), \
             mock.patch.object(sr, "index_archives", return_value={}), \
             mock.patch.object(sr, "recall_t1", return_value=[]), \
             mock.patch.object(sr, "recall_t2", return_value=[]), \
             mock.patch.object(sys, "argv",
                               ["session_recall.py", "zzz-no-such-thing"]), \
             contextlib.redirect_stdout(out), \
             contextlib.redirect_stderr(io.StringIO()):
            rc = sr.main()
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue(), "")


class StickyArtifactsTest(unittest.TestCase):
    BODY = "# Summary\n\nDid the deploy thing."

    def test_tail_roundtrip(self):
        remote = (self.BODY
                  + "\n\n## Artifacts\n\n### Files & paths\n\n"
                    "- `/x/y.py`\n\n### Commands run\n\n- `make deploy`\n")
        tail = sds._artifacts_tail(remote)
        self.assertTrue(tail.startswith("\n\n## Artifacts"))
        # reconstruction is byte-identical -> unchanged-check still hits
        self.assertEqual(self.BODY.rstrip() + tail, remote)

    def test_tail_stops_at_next_h2(self):
        remote = (self.BODY + "\n\n## Artifacts\n\n- `a`\n\n"
                  "## Appendix\n\n- `b`\n")
        tail = sds._artifacts_tail(remote)
        self.assertIn("## Artifacts", tail)
        self.assertNotIn("## Appendix", tail)

    def test_no_artifacts_empty(self):
        self.assertEqual(sds._artifacts_tail(self.BODY), "")


if __name__ == "__main__":
    unittest.main()
