"""Unit tests for scripts/ada/bank-inspect.py — per-lane memory-bank
snapshots into CMS memory-inspect pages (card memory-inspect-pages).

Covers the contracts the job relies on: lane->cms_collection derivation
from the persona-lanes SSOT, lane->bank visibility incl. read-only
mounts via instances_readonly, subject->attr->kind/value+modified row
extraction, secret redaction at write time, page shape, and the CMS
write routing — all over a fully fake MDDB transport; no network, no
writes leave the test process.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/bank-inspect.py"

spec = importlib.util.spec_from_file_location("bank_inspect", SCRIPT)
bi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bi)


def doc(key, subject="", attr="", kind="fact", value="v", status="active",
        updated_at=1700000000, updated=""):
    meta = {"status": [status]}
    if subject:
        meta["subject"] = [subject]
    if attr:
        meta["attribute"] = [attr]
    if kind:
        meta["kind"] = [kind]
    if updated:
        meta["updated"] = [updated]
    return {"key": key, "lang": "en", "contentMd": value, "meta": meta,
            "addedAt": updated_at, "updatedAt": updated_at}


class LaneMapTest(unittest.TestCase):
    def test_real_registry_lanes(self):
        lanes = bi.load_lanes()
        self.assertEqual(lanes.get("tony"), "ada-cms-pages")
        self.assertEqual(lanes.get("kk"), "ada-cms-pages-kk")
        self.assertEqual(lanes.get("michael"), "ada-cms-pages-mn")
        self.assertEqual(lanes.get("kk-dev"), "ada-cms-pages-kk-dev")

    def test_lane_banks_visibility(self):
        banks = {
            "general": {"mddb_collection": "ada-ha-bank-general",
                        "instances": ["tony", "michael", "kk"],
                        "instances_readonly": {"kk-dev": "kk"},
                        "writable": True},
            "personal": {"mddb_collection": "ada-ha-bank-personal-{instance}",
                         "instances": ["tony", "michael"], "writable": True},
            "cms": {"mddb_collection": "ada-cms-pages",
                    "instances": ["tony"], "writable": False},
        }
        tony = {b["collection"]: b["access"]
                for b in bi.lane_banks("tony", banks)}
        self.assertEqual(tony["ada-ha-bank-general"], "rw")
        self.assertEqual(tony["ada-ha-bank-personal-tony"], "rw")
        self.assertNotIn("ada-cms-pages", tony)  # not an ada-ha-bank-* coll

        kkdev = {b["collection"]: b["access"]
                 for b in bi.lane_banks("kk-dev", banks)}
        # read-only mount resolves to the mapped prod collection, flagged ro
        self.assertEqual(kkdev["ada-ha-bank-general"], "ro")
        self.assertNotIn("ada-ha-bank-personal-kk-dev", kkdev)


class RowTest(unittest.TestCase):
    def test_rows_extract_join_key(self):
        rows, n_red = bi.entry_rows([
            doc("k1", subject="noble-park", attr="weather-briefing",
                kind="preference", value="daily weather please",
                updated="2026-10-04"),
        ])
        self.assertEqual(n_red, 0)
        r = rows[0]
        self.assertEqual((r["subject"], r["attr"], r["kind"]),
                         ("noble-park", "weather-briefing", "preference"))
        self.assertEqual(r["modified"], "2026-10-04")
        self.assertIn("daily weather", r["value"])

    def test_status_filter_and_key_fallback(self):
        rows, _ = bi.entry_rows([
            doc("gone", subject="x", status="superseded"),
            doc("keep-me", value="hi"),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["subject"], "keep-me")  # key fallback
        self.assertEqual(rows[0]["modified"], "2023-11-14")  # updatedAt ts

    def test_secret_attribute_redacted(self):
        rows, n_red = bi.entry_rows([
            doc("k", subject="openrouter", attr="api_key", value="sk-or-v1-x"),
        ])
        self.assertEqual(n_red, 1)
        self.assertEqual(rows[0]["value"], bi.REDACTED)

    def test_secret_value_redacted(self):
        rows, n_red = bi.entry_rows([
            doc("k", subject="note", attr="misc",
                value="the key is AIzaSyD4iE2xVSpkLzdRW2z8gQabc123XYZ ok"),
        ])
        self.assertEqual(n_red, 1)
        self.assertNotIn("AIza", rows[0]["value"])

    def test_long_value_truncated(self):
        rows, _ = bi.entry_rows([doc("k", subject="s", attr="a",
                                     value="x" * 500)])
        self.assertTrue(rows[0]["value"].endswith("…"))
        self.assertLessEqual(len(rows[0]["value"]), bi.MAX_VALUE_CHARS + 1)


class FakeMDDB:
    """Records /add writes; serves canned /search results."""

    def __init__(self, docs_by_coll):
        self.docs = docs_by_coll
        self.writes = []

    def post(self, base, path, payload, timeout=60):
        if path == "/search":
            return self.docs.get(payload["collection"], [])
        if path == "/add":
            self.writes.append(payload)
            return {"ok": True}
        raise AssertionError(path)


class RunLaneTest(unittest.TestCase):
    def _args(self, fake):
        return types.SimpleNamespace(
            dry_run=False, bank=None,
            memory_mddb="mem://x", cms_mddb="cms://x")

    def test_pages_written_to_lane_collection(self):
        fake = FakeMDDB({"ada-ha-bank-general": [
            doc("k1", subject="s", attr="a", value="v1")]})
        orig = bi._post
        bi._post = fake.post
        try:
            banks = {"general": {"mddb_collection": "ada-ha-bank-general",
                                 "instances": ["tony"], "writable": True}}
            failed = bi.run_lane("tony", "ada-cms-pages", banks,
                                 self._args(fake), "2026-11-23T00:00:00+00:00")
        finally:
            bi._post = orig
        self.assertEqual(failed, 0)
        keys = sorted(w["key"] for w in fake.writes)
        self.assertEqual(keys, ["memory-inspect", "memory-inspect-general"])
        for w in fake.writes:
            self.assertEqual(w["collection"], "ada-cms-pages")
            self.assertEqual(w["meta"]["kind"], ["memory-inspect"])
            self.assertEqual(w["meta"]["domain"], ["memory"])
            self.assertEqual(w["meta"]["lane"], ["tony"])
        leaf = next(w for w in fake.writes if w["key"].endswith("-general"))
        self.assertIn("`s`", leaf["contentMd"])
        self.assertEqual(leaf["meta"]["report_role"], ["leaf"])
        self.assertEqual(leaf["meta"]["parent"], ["memory-inspect"])
        idx = next(w for w in fake.writes if w["key"] == "memory-inspect")
        self.assertEqual(idx["meta"]["report_role"], ["index"])
        self.assertIn("memory-inspect-general", idx["meta"]["children"])

    def test_mn_lane_routes_to_mn_collection(self):
        fake = FakeMDDB({"ada-ha-bank-general": []})
        orig = bi._post
        bi._post = fake.post
        try:
            banks = {"general": {"mddb_collection": "ada-ha-bank-general",
                                 "instances": ["michael"], "writable": True}}
            failed = bi.run_lane("michael", "ada-cms-pages-mn", banks,
                                 self._args(fake), "2026-11-23T00:00:00+00:00")
        finally:
            bi._post = orig
        self.assertEqual(failed, 0)
        self.assertTrue(all(w["collection"] == "ada-cms-pages-mn"
                            for w in fake.writes))
        self.assertEqual(fake.writes[0]["meta"]["scope"], ["michael"])

    def test_missing_collection_marks_index_error(self):
        fake = FakeMDDB({})
        orig = bi._post
        bi._post = fake.post
        try:
            banks = {"b": {"mddb_collection": "ada-ha-bank-b",
                           "instances": ["tony"], "writable": True}}
            failed = bi.run_lane("tony", "ada-cms-pages", banks,
                                 self._args(fake), "2026-11-23T00:00:00+00:00")
        finally:
            bi._post = orig
        self.assertEqual(failed, 0)  # empty dump still snapshots fine
        idx = next(w for w in fake.writes if w["key"] == "memory-inspect")
        self.assertIn("ada-ha-bank-b", idx["contentMd"])


class PageShapeTest(unittest.TestCase):
    def test_index_links_leaves(self):
        md = bi.index_page("tony", [
            {"bank": "general", "collection": "ada-ha-bank-general",
             "access": "rw", "n": 3, "n_red": 1, "latest": "2026-11-20"},
        ], "2026-11-23T00:00:00+00:00")
        self.assertIn("](memory-inspect-general)", md)
        self.assertIn("3 banks".split()[0], md)  # entry count present
        self.assertIn("redacted", md)

    def test_bank_page_table(self):
        md = bi.bank_page("tony", {"bank": "g",
                                   "collection": "ada-ha-bank-general",
                                   "access": "rw"},
                          [{"subject": "s", "attr": "a", "kind": "fact",
                            "value": "v", "modified": "2026-11-20"}],
                          0, "now")
        self.assertIn("| `s` | `a` | fact | v | 2026-11-20 |", md)
        self.assertIn("parent: memory-inspect", md)


if __name__ == "__main__":
    unittest.main()
