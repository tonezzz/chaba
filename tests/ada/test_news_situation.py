"""Unit tests for the news-situation flag machinery (card
news-situation-summaries): the watching|pinned ladder, the meta-vs-tag
effective state, member comment command parsing in wp-comment-sync, and
the situations index renderer. Pure functions + a stub WP — no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ns = load("news_situation", "scripts/ada/news-situation.py")
wcs = load("wp_comment_sync", "scripts/ada/wp-comment-sync.py")


class FakeWP:
    """Records api() writes; resolves tag names/ids bidirectionally."""

    def __init__(self):
        self.writes = []
        self.names = {1: "digest", 2: "sources:4"}
        self.ids = {v: k for k, v in self.names.items()}
        self._next = 100

    def api(self, route, data=None, method=None):
        if data is not None:
            self.writes.append((route, data))
        return {}

    def tag_names(self, ids):
        return [self.names.get(i, str(i)) for i in ids]

    def tag_ids(self, names):
        out = []
        for n in names:
            if n not in self.ids:
                self.ids[n] = self._next
                self.names[self._next] = n
                self._next += 1
            out.append(self.ids[n])
        return out


def post(pid=7, meta=None, tags=None, title="Digest — flood", content=""):
    return {"id": pid, "meta": meta or {}, "tags": tags or [],
            "title": {"rendered": title}, "link": "https://x/p",
            "content": {"rendered": content}}


class LadderTest(unittest.TestCase):
    def test_promote(self):
        self.assertEqual(ns.promote_step(""), "watching")
        self.assertEqual(ns.promote_step("watching"), "pinned")
        self.assertEqual(ns.promote_step("pinned"), "pinned")

    def test_demote(self):
        self.assertEqual(ns.demote_step("pinned"), "watching")
        self.assertEqual(ns.demote_step("watching"), "")
        self.assertEqual(ns.demote_step(""), "")


class EffectiveStateTest(unittest.TestCase):
    def test_meta_wins(self):
        p = post(meta={"situation": "pinned"}, tags=[1])
        p["_tag_names"] = ["digest", "situation-watching"]
        self.assertEqual(ns.effective_state(p), "pinned")

    def test_tag_fallback(self):
        p = post(tags=[1])
        p["_tag_names"] = ["digest", "situation-pinned"]
        self.assertEqual(ns.effective_state(p), "pinned")

    def test_unflagged(self):
        p = post(meta={"situation": "bogus"}, tags=[1])
        p["_tag_names"] = ["digest"]
        self.assertEqual(ns.effective_state(p), "")


class SetStateTest(unittest.TestCase):
    def test_pin_writes_meta_tag_sticky(self):
        wp = FakeWP()
        p = post(meta={"situation": "watching"}, tags=[1, 2])
        p["_tag_names"] = ["digest", "sources:4", "situation-watching"]
        # tag ids: 99 = situation-watching already mirrored
        wp.names[99] = "situation-watching"
        wp.ids["situation-watching"] = 99
        p["tags"] = [1, 2, 99]
        old, new, changed = ns.set_state(wp, p, "pinned",
                                         by="comment:tony", dry_run=False)
        self.assertEqual((old, new, changed), ("watching", "pinned", True))
        route, data = wp.writes[0]
        self.assertEqual(route, "/wp/v2/news/7")
        self.assertEqual(data["meta"]["situation"], "pinned")
        self.assertEqual(data["meta"]["situation_by"], "comment:tony")
        self.assertTrue(data.get("sticky"))
        # tag mirror swapped: watching tag gone, pinned tag present
        self.assertNotIn(99, data["tags"])
        self.assertIn(wp.ids["situation-pinned"], data["tags"])
        # unrelated tags preserved
        self.assertIn(1, data["tags"])
        self.assertIn(2, data["tags"])
        # never silent: a comment trail was posted
        comments = [d for r, d in wp.writes if r == "/wp/v2/comments"]
        self.assertTrue(comments)
        self.assertIn("watching → pinned", comments[0]["content"])

    def test_clear_removes_tag_and_sticky(self):
        wp = FakeWP()
        wp.names[99] = "situation-pinned"
        wp.ids["situation-pinned"] = 99
        p = post(meta={"situation": "pinned"}, tags=[1, 99])
        p["_tag_names"] = ["digest", "situation-pinned"]
        old, new, changed = ns.set_state(wp, p, "", by="cli")
        self.assertEqual(new, "")
        _, data = wp.writes[0]
        self.assertEqual(data["meta"]["situation"], "")
        self.assertFalse(data.get("sticky", True))
        self.assertNotIn(99, data["tags"])

    def test_idempotent(self):
        wp = FakeWP()
        p = post(meta={"situation": "watching"}, tags=[1])
        p["_tag_names"] = ["digest"]
        self.assertEqual(ns.set_state(wp, p, "watching")[2], False)
        self.assertEqual(wp.writes, [])

    def test_tag_only_flag_backfills_meta(self):
        # pre-0.6.0 flag: tag holds watching, registered meta is empty
        wp = FakeWP()
        wp.names[99] = "situation-watching"
        wp.ids["situation-watching"] = 99
        p = post(meta={"situation": "", "situation_by": ""}, tags=[1, 99])
        p["_tag_names"] = ["digest", "situation-watching"]
        old, new, changed = ns.set_state(wp, p, "watching")
        self.assertEqual((old, new, changed), ("watching", "watching", False))
        self.assertEqual(len(wp.writes), 1)
        route, data = wp.writes[0]
        self.assertEqual(route, "/wp/v2/news/7")
        self.assertEqual(data["meta"]["situation"], "watching")
        self.assertEqual(data["meta"]["situation_by"], "tag-sync")
        # convergence is silent — no comment posted
        self.assertFalse([d for r, d in wp.writes
                          if r == "/wp/v2/comments"])

    def test_no_backfill_when_meta_present(self):
        wp = FakeWP()
        p = post(meta={"situation": "watching"}, tags=[1])
        p["_tag_names"] = ["digest", "situation-watching"]
        self.assertFalse(ns.sync_meta_from_tag(wp, p, "watching"))
        self.assertEqual(wp.writes, [])


class SweepTest(unittest.TestCase):
    def test_sweep_backfills_tag_only_flags(self):
        wp = FakeWP()
        wp.names[99] = "situation-watching"
        wp.ids["situation-watching"] = 99

        flagged = post(pid=7, meta={}, tags=[99])
        flagged["_tag_names"] = ["situation-watching"]
        quiet = post(pid=8, meta={}, tags=[1])
        quiet["_tag_names"] = ["digest"]

        posts = [flagged, quiet]
        args = argparse.Namespace(sources=3, dry_run=False)
        orig_digest = ns.digest_posts
        try:
            ns.digest_posts = lambda w: posts
            ns.cmd_sweep(wp, args)
        finally:
            ns.digest_posts = orig_digest
        metas = [d["meta"] for r, d in wp.writes if r == "/wp/v2/news/7"]
        self.assertEqual(metas[0]["situation"], "watching")


class CommentCommandTest(unittest.TestCase):
    def test_english(self):
        self.assertEqual(wcs.parse_situation_command("pin this"), "pinned")
        self.assertEqual(wcs.parse_situation_command("watch"), "watching")
        self.assertEqual(wcs.parse_situation_command("unpin please"),
                         wcs.DEMOTE)
        self.assertEqual(wcs.parse_situation_command("unwatch"), "")

    def test_thai(self):
        self.assertEqual(wcs.parse_situation_command("ปักหมุด"), "pinned")
        self.assertEqual(wcs.parse_situation_command("เฝ้าระวังอันนี้"),
                         "watching")
        self.assertEqual(wcs.parse_situation_command("เลิกปักหมุด"),
                         wcs.DEMOTE)
        self.assertEqual(wcs.parse_situation_command("เลิกติดตามข่าวนี้"), "")

    def test_non_command(self):
        self.assertIsNone(wcs.parse_situation_command("interesting story"))
        self.assertIsNone(wcs.parse_situation_command(""))
        self.assertIsNone(wcs.parse_situation_command(None))
        # narrative mention past the command window doesn't fire
        self.assertIsNone(wcs.parse_situation_command(
            "this long comment talks about the news article and only at "
            "the very end asks the system to pin it"))

    def test_unpin_beats_pin(self):
        # substring check: "เลิกปักหมุด" contains "ปักหมุด" — demote,
        # not pin
        self.assertEqual(wcs.parse_situation_command("เลิกปักหมุดหน่อย"),
                         wcs.DEMOTE)


class IndexRenderTest(unittest.TestCase):
    def test_sections_and_thai_first(self):
        rows = [
            {"id": 1, "state": "watching", "meta": {"brief_th": "กำลังเฝ้าระวัง"},
             "sources": 3, "since": "2026-10-15 10:00", "by": "auto-nominate",
             "title": "Digest — floods", "link": "https://x/1"},
            {"id": 2, "state": "pinned", "meta": {"brief_th": "ปักหมุดไว้"},
             "sources": 5, "since": "", "by": "tony",
             "title": "Digest — dam", "link": "https://x/2"},
        ]
        out = ns.render_index(None, rows)
        self.assertIn("ปักหมุด", out)          # pinned section
        self.assertIn("เฝ้าระวัง", out)        # watching section
        self.assertIn("กำลังเฝ้าระวัง", out)   # thai brief rendered
        self.assertLess(out.index("ปักหมุดไว้"), out.index("กำลังเฝ้าระวัง"))

    def test_empty(self):
        self.assertIn("ไม่มีสถานการณ์", ns.render_index(None, []))


class BriefThTest(unittest.TestCase):
    TH = ('<p>en brief</p><p class="brief-th" lang="th">'
          "<strong>สรุป:</strong> น้ำท่วม 20 จังหวัด กทม. เร่งระบาย</p>")

    def test_meta_wins(self):
        p = post(meta={"brief_th": "จากเมทา"}, content=self.TH)
        self.assertEqual(ns.brief_th_of(p), "จากเมทา")

    def test_content_fallback(self):
        self.assertEqual(ns.brief_th_of(post(content=self.TH)),
                         "น้ำท่วม 20 จังหวัด กทม. เร่งระบาย")

    def test_absent(self):
        self.assertEqual(ns.brief_th_of(post(content="<p>en only</p>")), "")


if __name__ == "__main__":
    unittest.main()
