"""Unit tests for scripts/ada/ops-error-posts.py — the Ada tool/stream
failure -> WP ops_error writer (card boards-error-post-type).

Covers the no-network contracts: result classification into the CPT's
error_type enum (incl. the confirm-gate / ACL skips), journald row
parsing (received/result arg join, session tracking, resumed=False
reconnects), slug dedup shape (silent_reconnect coalesces per
session-day), and the title convention from ssot.wp-boards.yml.
"""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/ops-error-posts.py"

spec = importlib.util.spec_from_file_location("ops_error_posts", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

T0 = datetime(2026, 10, 13, 16, 16, 40, tzinfo=timezone.utc).timestamp()


def row(ts, line):
    return {"ts_epoch": ts, "line": line}


JOURNAL = [
    row(T0, "2026-10-13 16:16:40,000 INFO voice.provider: "
            "session=183e9c8d7e function_call received id=call_1 "
            "name=web_search args={}"),
    row(T0 + 1, "2026-10-13 16:16:41,000 INFO voice.provider: "
                "session=183e9c8d7e function_call result id=call_1 "
                "name=web_search result={'ok': False, 'error': "
                "\"SchemaError: missing required 'query'\", "
                "'usage': 'web_search(query: str)'}"),
    row(T0 + 2, "2026-10-13 16:16:42,000 INFO voice.provider: "
                "session=183e9c8d7e provider reconnected "
                "(resumed=False) — context wiped"),
]


class ClassifyTest(unittest.TestCase):
    def test_schema_error_text(self):
        self.assertEqual(m.classify_result(
            "result={'ok': False, 'error': \"SchemaError: missing 'query'\"}",
            {"ok": False, "error": "SchemaError: missing 'query'"}),
            "schema_error")

    def test_schema_error_via_usage_key(self):
        self.assertEqual(m.classify_result(
            "result={'ok': False, 'error': 'bad call', 'usage': 'f(x)'}",
            {"ok": False, "error": "bad call", "usage": "f(x)"}),
            "schema_error")

    def test_schema_error_arg_rejection(self):
        self.assertEqual(m.classify_result(
            "result={'ok': False, 'error': 'invalid action x'}",
            {"ok": False, "error": "invalid action x"}),
            "schema_error")

    def test_runtime_error(self):
        self.assertEqual(m.classify_result(
            "result={'ok': False, 'error': 'HTTP 502 from vcast relay'}",
            {"ok": False, "error": "HTTP 502 from vcast relay"}),
            "runtime_error")

    def test_degraded(self):
        self.assertEqual(m.classify_result(
            "result={'ok': True, 'degraded': True}",
            {"ok": True, "degraded": True}), "degraded_result")

    def test_stale(self):
        self.assertEqual(m.classify_result(
            "result={'ok': True, 'stale': True}",
            {"ok": True, "stale": True}), "stale_result")

    def test_confirm_and_acl_skipped(self):
        self.assertIsNone(m.classify_result(
            "result={'error': 'NOT EXECUTED — requires confirmation'}",
            {"error": "NOT EXECUTED — requires confirmation"}))
        self.assertIsNone(m.classify_result(
            "result={'ok': False, 'error': 'Only the session owner can "
            "run this action'}",
            {"ok": False,
             "error": "Only the session owner can run this action"}))

    def test_clean_result_none(self):
        self.assertIsNone(m.classify_result(
            "result={'ok': True, 'data': {}}", {"ok": True}))

    def test_unparsed_truncated_line(self):
        self.assertEqual(m.classify_result(
            "result={'ok': False, 'error': 'boom {truncated", None),
            "runtime_error")


class JournalParseTest(unittest.TestCase):
    def test_pairs_args_into_raw(self):
        evs = m.parse_journal_events(JOURNAL, "kk")
        ws = next(e for e in evs if e["tool"] == "web_search")
        self.assertEqual(ws["error_type"], "schema_error")
        self.assertIn('"_call_args": {}', ws["raw_result"])

    def test_reconnect_classified(self):
        evs = m.parse_journal_events(JOURNAL, "kk")
        rec = next(e for e in evs if e["error_type"] == "silent_reconnect")
        self.assertEqual(rec["session_id"], "183e9c8d7e")
        self.assertEqual(rec["tool"], "stream")

    def test_reconnect_inherits_last_session(self):
        rows = JOURNAL + [
            row(T0 + 5, "2026-10-13 16:16:45,000 INFO voice.provider: "
                        "prime injected (resumed=False)")]
        evs = m.parse_journal_events(rows, "kk")
        recs = [e for e in evs if e["error_type"] == "silent_reconnect"]
        self.assertTrue(all(e["session_id"] == "183e9c8d7e" for e in recs))

    def test_session_filter(self):
        evs = m.parse_journal_events(JOURNAL, "kk",
                                     session_filter="183e9c8d7e")
        self.assertEqual(len(evs), 2)
        self.assertEqual(m.parse_journal_events(
            JOURNAL, "kk", session_filter="other99"), [])


class SlugTitleTest(unittest.TestCase):
    def _ev(self, **kw):
        e = {"lane": "kk", "session_id": "s1", "tool": "web_search",
             "error_type": "schema_error", "occurred_at": T0,
             "raw_result": "{}", "transcript_ref": "", "evidence": "x"}
        e.update(kw)
        return e

    def test_slug_distinct_per_event(self):
        a = self._ev()
        b = self._ev(occurred_at=T0 + 60)
        self.assertNotEqual(m.event_slug(a), m.event_slug(b))

    def test_reconnect_coalesces_per_day(self):
        a = self._ev(error_type="silent_reconnect", tool="stream")
        b = self._ev(error_type="silent_reconnect", tool="stream",
                     occurred_at=T0 + 3600)
        self.assertEqual(m.event_slug(a), m.event_slug(b))

    def test_title_convention(self):
        self.assertEqual(
            m.event_title(self._ev()), "Err — kk web_search 2026-10-13")
        self.assertEqual(
            m.event_title(self._ev(tool="", error_type="silent_reconnect")),
            "Err — kk stream 2026-10-13")

    def test_content_mentions_review_loop(self):
        c = m.event_content(self._ev())
        self.assertIn("status=resolved", c)
        self.assertIn("s1", c)


if __name__ == "__main__":
    unittest.main()
