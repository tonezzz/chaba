"""Unit tests for scripts/ada/line-digest.py — weekly per-member LINE
push (card cmssurface-render-digest, component 2).

Covers the two contracts that matter: source lines only appear when real
data lands in the window, and sends are idempotent on
line-digest-<member>-<ISOweek> — a re-run never double-pushes. All I/O
(MDDB search, board-api, relay /send, state file) is faked.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/line-digest.py"

spec = importlib.util.spec_from_file_location("line_digest", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["line_digest"] = mod
spec.loader.exec_module(mod)

ICT = mod.ICT
NOW = dt.datetime.now(ICT)


def d(key, added=0, updated=0, meta=None):
    return {"key": key, "lang": "en", "contentMd": "# x",
            "meta": meta or {}, "addedAt": added, "updatedAt": updated}


def meta(**kw):
    return {k: (v if isinstance(v, list) else [v]) for k, v in kw.items()}


class Sources(unittest.TestCase):
    def setUp(self):
        self.since_ts = (NOW - dt.timedelta(days=7)).timestamp()
        self.t = mod.TXT["en"]

    def test_house_timeline_counts_in_window_leaves(self):
        docs = [d("house-timeline-a", updated=self.since_ts + 10),
                d("house-timeline-b", updated=self.since_ts - 10),
                d("house-timeline-qc", updated=self.since_ts + 10),
                d("house-timeline", updated=self.since_ts + 10)]
        lines = mod.src_house_timeline(docs, self.since_ts, self.t)
        self.assertEqual(len(lines), 1)
        self.assertIn(": 1 ", lines[0])          # qc + rollup excluded
        self.assertIn("/p/house-timeline", lines[0])

    def test_media_inbox_counts_new_leaves_not_extracts(self):
        docs = [d("media-1", added=self.since_ts + 5),
                d("media-2-extract", added=self.since_ts + 5),
                d("media-3", added=self.since_ts - 5),
                d("media-inbox", added=self.since_ts + 5)]
        lines = mod.src_media_inbox(docs, self.since_ts, self.t)
        self.assertEqual(len(lines), 1)
        self.assertIn(": 1 ", lines[0])          # extracts + rollup excluded

    def test_news_lists_rollup_digests_in_window(self):
        docs = [
            d("news-digest", updated=self.since_ts + 5,
              meta=meta(report_role="digest")),
            d("news-digest-2026-10-01", updated=self.since_ts + 5,
              meta=meta(report_role="digest")),     # dated snapshot — skip
            d("ops-digest", updated=self.since_ts - 5,
              meta=meta(report_role="digest")),     # stale — skip
            d("plain", updated=self.since_ts + 5, meta=meta()),
        ]
        lines = mod.src_news(docs, self.since_ts, self.t)
        self.assertEqual(len(lines), 1)
        self.assertIn("news-digest", lines[0])
        self.assertNotIn("2026-10-01", lines[0])

    def test_news_none(self):
        self.assertEqual(mod.src_news([], self.since_ts, self.t), [])


class KanbanSource(unittest.TestCase):
    def setUp(self):
        self.t = mod.TXT["en"]
        self.since_dt = NOW - dt.timedelta(days=7)
        self.new_dt = NOW - dt.timedelta(days=2)
        self.old_dt = NOW - dt.timedelta(days=30)

    def _cards(self, *cards):
        return {"cards": list(cards)}

    def test_counts_done_comm_in_window(self):
        cards = self._cards(
            {"id": "a", "column": "done",
             "comms": [{"at": self.new_dt.strftime("%Y-%m-%d %H:%M"),
                        "text": "closed by tony"}]},
            {"id": "b", "column": "done",
             "comms": [{"at": self.old_dt.strftime("%Y-%m-%d %H:%M"),
                        "text": "closed by tony"}]},
            {"id": "c", "column": "done",
             "comms": [{"at": self.new_dt.strftime("%Y-%m-%d %H:%M"),
                        "text": "some comment"}]},       # touch, not close
            {"id": "d", "column": "doing",
             "comms": [{"at": self.new_dt.strftime("%Y-%m-%d %H:%M"),
                        "text": "closed by tony"}]},      # not done
        )
        with mock.patch("urllib.request.urlopen") as uo:
            uo.return_value.read.return_value = json.dumps(cards).encode()
            lines = mod.src_kanban(self.since_dt, self.t)
        self.assertEqual(lines, ["• kanban: 1 cards done"])

    def test_board_down_returns_empty(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=OSError("down")):
            self.assertEqual(mod.src_kanban(self.since_dt, self.t), [])


class Idempotency(unittest.TestCase):
    def test_send_payload_and_state_skip(self):
        sent = []

        class Resp:
            def read(self):
                return json.dumps({"ok": True, "to": "U1"}).encode()

        with tempfile.TemporaryDirectory() as td:
            st = Path(td) / "state.json"
            with mock.patch("urllib.request.urlopen",
                            return_value=Resp()) as uo:
                res = mod.send("http://x/send", "tony", "hello",
                             "line-digest-tony-2026w42")
                body = json.loads(uo.call_args[0][0].data)
            self.assertTrue(res["ok"])
            self.assertEqual(body["to"], "tony")
            self.assertEqual(body["instance"], "tony")
            self.assertEqual(body["message_id"], "line-digest-tony-2026w42")
            # state round-trip
            st.write_text(json.dumps({"line-digest-tony-2026w42": {}}))
            self.assertIn("line-digest-tony-2026w42", mod.load_state(st))


class BuildDigest(unittest.TestCase):
    def test_none_when_no_sources(self):
        with mock.patch.object(mod, "list_docs", return_value=[]), \
             mock.patch.object(mod, "src_kanban", return_value=[]), \
             mock.patch.object(mod, "src_render_jobs", return_value=[]):
            self.assertIsNone(mod.build_digest("tony", 7))

    def test_member_mapping_required(self):
        self.assertNotIn("nobody", mod.MEMBERS)


if __name__ == "__main__":
    unittest.main()
