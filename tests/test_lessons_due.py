"""Unit tests for scripts/lessons-due.py — pure row/bucket/render
functions plus the source=wiki door contract (stale-door guard, write
payload shape). No network: door_post is faked.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "board"))

spec = importlib.util.spec_from_file_location(
    "lessons_due", REPO / "scripts" / "lessons-due.py")
ld = importlib.util.module_from_spec(spec)
sys.modules["lessons_due"] = ld
spec.loader.exec_module(ld)

ROWS = [
    {"slug": "lesson-a", "topic": "alpha", "level": "intro",
     "next_review": "2026-11-01", "status": "open",
     "href": "https://x/a", "wiki_title": "Education:Alpha"},
    {"slug": "lesson-b", "topic": "beta", "level": "deep",
     "next_review": "2026-12-01", "status": "open",
     "href": "https://x/b", "wiki_title": "Education:Beta"},
    {"slug": "lesson-c", "topic": "gamma", "level": "working",
     "next_review": "2026-10-01", "status": "learned",
     "href": "https://x/c", "wiki_title": "Education:Gamma"},
    {"slug": "lesson-d", "topic": "delta", "level": "intro",
     "next_review": "", "status": "open",
     "href": "", "wiki_title": ""},
]
TODAY = "2026-11-06"


class BucketTest(unittest.TestCase):
    def test_review_buckets(self):
        self.assertEqual(ld.review_bucket(
            {"status": "learned"}, TODAY), "learned")
        self.assertEqual(ld.review_bucket(
            {"next_review": "2026-11-01"}, TODAY), "due")
        self.assertEqual(ld.review_bucket(
            {"next_review": "2026-12-01"}, TODAY), "upcoming")
        # no next_review -> upcoming (R1 flags it, not this queue)
        self.assertEqual(ld.review_bucket({}, TODAY), "upcoming")

    def test_bucket_rows_sort_and_exclude(self):
        due, upcoming = ld.bucket_rows(ROWS, TODAY)
        self.assertEqual([r["slug"] for r in due], ["lesson-a"])
        self.assertEqual([r["slug"] for r in upcoming],
                         ["lesson-d", "lesson-b"])   # "" sorts first


class RenderTest(unittest.TestCase):
    def test_due_wikitext(self):
        due, upcoming = ld.bucket_rows(ROWS, TODAY)
        wt = ld.due_wikitext(due, upcoming, TODAY)
        self.assertIn("== Due now (1) ==", wt)
        self.assertIn("[[Education:Alpha|alpha]] — due 2026-11-01 "
                      "(intro)", wt)
        self.assertIn("[[Education:Beta|beta]] — 2026-12-01", wt)
        self.assertIn("* delta — ", wt)          # no wiki_title -> plain
        self.assertIn("[[Category:Education]]", wt)
        self.assertNotIn("gamma", wt)            # learned excluded

    def test_due_wikitext_empty(self):
        wt = ld.due_wikitext([], [], TODAY)
        self.assertIn("Nothing due", wt)

    def test_due_html(self):
        due, upcoming = ld.bucket_rows(ROWS, TODAY)
        html = ld.due_html(due, upcoming, TODAY)
        self.assertIn("<h3>Due now (1)</h3>", html)
        self.assertIn('href="https://x/a"', html)
        self.assertIn("beta — 2026-12-01", html)


class DoorContractTest(unittest.TestCase):
    def _fake_door(self, response):
        sent = []

        def fake(api_base, path, body):
            sent.append((path, body))
            return response
        return sent, fake

    def test_fetch_rows_wiki(self):
        sent, fake = self._fake_door({
            "source": "wiki", "count": 1,
            "lessons": [{"slug": "lesson-a", "topic": "alpha",
                         "level": "intro", "next_review": "2026-11-01",
                         "status": "open",
                         "wiki_title": "Education:Alpha",
                         "url": "https://wiki/x"}]})
        real = ld.door_post
        ld.door_post = fake
        try:
            rows = ld.fetch_rows("wiki", "http://door")
        finally:
            ld.door_post = real
        self.assertEqual(sent[0][0], "/lesson")
        self.assertEqual(sent[0][1]["op"], "list")
        self.assertEqual(sent[0][1]["source"], "wiki")
        self.assertEqual(rows[0]["href"], "https://wiki/x")

    def test_fetch_rows_wiki_stale_door(self):
        # A door that predates the wiki read path ignores "source" and
        # answers a WP-shaped list — fail loudly, never audit WP rows
        # under a wiki label.
        _sent, fake = self._fake_door({"lessons": [], "count": 0})
        real = ld.door_post
        ld.door_post = fake
        try:
            with self.assertRaises(RuntimeError):
                ld.fetch_rows("wiki", "http://door")
        finally:
            ld.door_post = real

    def test_write_wiki_payload(self):
        sent, fake = self._fake_door(
            {"action": "success", "wiki_title": "Education:Due",
             "revid": 9})
        real = ld.door_post
        ld.door_post = fake
        try:
            msg = ld.write_wiki("http://door", "== x ==")
        finally:
            ld.door_post = real
        path, body = sent[0]
        self.assertEqual(path, "/wiki/page")
        self.assertEqual(body["title"], "Education:Due")
        self.assertEqual(body["wikitext"], "== x ==")
        self.assertIn("success", msg)

    def test_door_post_injects_from(self):
        """Every door call carries the actor name — board-api 400s
        without one (the phase-3 --apply bug)."""
        import io, json as _json, urllib.request as ur
        sent = {}

        class Resp:
            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(req, timeout=0):
            sent["url"] = req.full_url
            sent["body"] = _json.loads(req.data)
            return Resp()
        real = ur.urlopen
        ur.urlopen = fake_urlopen
        try:
            r = ld.door_post("http://door", "/lesson",
                             {"op": "list", "source": "wiki"})
        finally:
            ur.urlopen = real
        self.assertTrue(r["ok"])
        self.assertEqual(sent["url"], "http://door/lesson")
        self.assertEqual(sent["body"]["from"], "lessons-due")
        self.assertEqual(sent["body"]["source"], "wiki")


if __name__ == "__main__":
    unittest.main()
