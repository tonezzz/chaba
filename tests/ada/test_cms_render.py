"""Unit tests for apps/cms-render/server.py — the live MDDB->HTML
presentation layer (card cmssurface-render-digest).

Covers the contracts the service relies on: meta1 extraction over MDDB's
list-valued meta, render-kind dispatch per slug family, the CMS-markdown
extensions (```media / ```mermaid blocks, #/slug link rewriting), the
updatedAt-keyed page cache, slug->key resolution with collection + lang
fallbacks, and the HTTP routes over a fully fake MDDB transport — no
network, no writes leave the test process.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "apps/cms-render/server.py"

spec = importlib.util.spec_from_file_location("cms_render", SERVER)
srv = importlib.util.module_from_spec(spec)
sys.modules["cms_render"] = srv
try:
    spec.loader.exec_module(srv)
except ModuleNotFoundError as e:  # deps live in the app venv, not every host
    raise unittest.SkipTest(
        f"cms-render deps missing ({e}) — install "
        "apps/cms-render/requirements.txt to run this suite")


def doc(key, coll="ada-cms-pages", lang="en", md="# x", meta=None,
        updated_at=1000):
    return {"id": f"{coll}|{key}|{lang}", "key": key, "lang": lang,
            "contentMd": md, "meta": meta or {}, "addedAt": updated_at,
            "updatedAt": updated_at}


def meta(**kw):
    return {k: (v if isinstance(v, list) else [v]) for k, v in kw.items()}


class FakeMDDB:
    """In-process MDDB: /get + paginated /search for the four CMS
    collections."""

    def __init__(self):
        self.docs = {}  # (coll, key, lang) -> doc

    def seed(self, key, coll="ada-cms-pages", lang="en", md="# x",
             meta_=None, updated_at=1000):
        d = doc(key, coll, lang, md, meta_, updated_at)
        self.docs[(coll, key, lang)] = d
        return d

    def handle(self, path, payload, timeout=30):
        coll = payload.get("collection")
        if path == "get":
            return self.docs.get((coll, payload.get("key"),
                                  payload.get("lang")))
        if path == "search":
            limit = payload.get("limit", 500)
            off = payload.get("offset", 0)
            out = [d for (c, _k, _l), d in sorted(self.docs.items())
                   if c == coll]
            return out[off:off + limit]
        raise AssertionError(f"unexpected path {path}")


class MetaHelpers(unittest.TestCase):
    def test_meta1_list_scalar_missing(self):
        self.assertEqual(srv.meta1({"a": ["x", "y"]}, "a"), "x")
        self.assertEqual(srv.meta1({"a": "s"}, "a"), "s")
        self.assertEqual(srv.meta1({}, "a"), "")
        self.assertEqual(srv.meta1({"a": []}, "a", "d"), "d")

    def test_detect_kind_families(self):
        cases = [
            ("place-foo", "ada-cms-pages", "page", "", "place-report"),
            ("trip-sa", "ada-cms-pages", "report", "rollup", "trip"),
            ("x", "ada-cms-pages", "page", "", "trip"),          # domain travel
            ("house-rules", "ada-cms-pages", "page", "", "house-rules"),
            ("media-1", "ada-cms-pages", "report", "leaf", "media-inbox"),
            ("media-inbox", "ada-cms-pages", "report", "rollup",
             "media-inbox"),
            ("house-timeline-x", "ada-cms-pages", "report", "leaf",
             "timeline"),
            ("news-digest", "ada-cms-pages", "report", "digest", "digest"),
            ("anything", "ada-cms-pages", "report", "", "report"),
            ("anything", "ada-cms-pages", "page", "", "page"),
            ("cfg", "ada-cms-automation", "automation-config", "",
             "automation"),
            ("api/x.md", "chaba-docs", "", "", "doc"),
        ]
        for key, coll, kind, role, want in cases:
            m = meta(kind=kind, report_role=role,
                     domain="travel" if want == "trip" and key == "x"
                     else "ops")
            got = srv.detect_kind(doc(key, coll=coll, meta=m), coll)
            self.assertEqual(got, want, f"{key}/{coll}")


class MarkdownTests(unittest.TestCase):
    def test_media_block_video(self):
        md = ('## Preview\n```media\n{"url": "https://x/v.mp4", '
              '"type": "video", "caption": "clip"}\n```')
        out, has_mer = srv.md_to_html(md, "ada-cms-pages")
        self.assertIn('<video controls preload="metadata" '
                      'src="https://x/v.mp4">', out)
        self.assertIn("<figcaption>clip</figcaption>", out)
        self.assertFalse(has_mer)

    def test_media_block_audio_and_bad_body(self):
        out, _ = srv.md_to_html(
            '```media\n{"url": "https://x/a.m4a", "type": "audio"}\n```',
            "ada-cms-pages")
        self.assertIn("<audio", out)
        out, _ = srv.md_to_html("```media\nnot json\n```", "ada-cms-pages")
        self.assertNotIn("figure", out)  # no url -> dropped

    def test_mermaid_block(self):
        md = "```mermaid\ngantt\n    title T\n```"
        out, has_mer = srv.md_to_html(md, "ada-cms-pages")
        self.assertIn('<pre class="mermaid">', out)
        self.assertIn("gantt", out)
        self.assertTrue(has_mer)

    def test_internal_link_rewrite(self):
        md = "[leaf](#/media-1) [![t](https://img/t.jpg)](#/media-2)"
        out, _ = srv.md_to_html(md, "ada-cms-pages")
        self.assertIn('href="/p/media-1"', out)
        self.assertIn('src="https://img/t.jpg"', out)
        # kk collection pins ?c= so same-slug pages don't hijack links
        out, _ = srv.md_to_html("[leaf](#/media-1)", "ada-cms-pages-kk")
        self.assertIn('href="/p/media-1?c=ada-cms-pages-kk"', out)

    def test_table_and_code_passthrough(self):
        md = "| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nx=1\n```"
        out, _ = srv.md_to_html(md, "ada-cms-pages")
        self.assertIn("<table>", out)
        self.assertIn("<code", out)


class CacheTests(unittest.TestCase):
    def test_page_cache_keyed_by_updated(self):
        c = srv.PageCache(maxsize=4)
        k = ("coll", "key", "en")
        c.put(k, 111, "html-v1")
        self.assertEqual(c.get(k, 111), "html-v1")
        self.assertIsNone(c.get(k, 222))       # doc changed -> miss
        self.assertIsNone(c.get(k, 0))         # missing ts -> miss

    def test_listing_caches_and_slug_map(self):
        fake = FakeMDDB()
        fake.seed("real-key", meta_=meta(slug="nice-slug"))
        calls = []
        orig = srv.list_docs
        srv.list_docs = lambda c, limit=500: (calls.append(c),
                                              fake.handle("search", {
                                                  "collection": c,
                                                  "limit": limit}))[1]
        try:
            lc = srv.ListingCache(ttl=60)
            self.assertEqual(lc.slug_map("ada-cms-pages"),
                             {"nice-slug": "real-key"})
            lc.slug_map("ada-cms-pages")      # cached — one scan only
            self.assertEqual(len(calls), 1)
        finally:
            srv.list_docs = orig


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMDDB()
        self.orig_post, self.orig_listing = srv._post, srv.LISTING
        srv._post = self.fake.handle
        srv.LISTING = srv.ListingCache(ttl=60)

    def tearDown(self):
        srv._post, srv.LISTING = self.orig_post, self.orig_listing

    def test_key_hit(self):
        self.fake.seed("a-page", meta_=meta(slug="a-page", kind="page"))
        coll, key, d, langs = srv.resolve("a-page")
        self.assertEqual((coll, key), ("ada-cms-pages", "a-page"))
        self.assertEqual(d["key"], "a-page")

    def test_slug_to_key(self):
        self.fake.seed("ugly-2026-10-15", meta_=meta(slug="pretty"))
        coll, key, d, _ = srv.resolve("pretty")
        self.assertEqual(key, "ugly-2026-10-15")

    def test_collection_hint_and_lang(self):
        self.fake.seed("kk-page", coll="ada-cms-pages-kk", lang="th",
                       meta_=meta(slug="kk-page"))
        self.fake.seed("kk-page", coll="ada-cms-pages", lang="en",
                       meta_=meta(slug="kk-page"))
        # hint pins the kk lane doc
        coll, key, d, langs = srv.resolve("kk-page", coll_hint="ada-cms-pages-kk")
        self.assertEqual((coll, d["lang"]), ("ada-cms-pages-kk", "th"))
        self.assertIn("th", langs)
        # lang pick overrides collection default
        coll, key, d, langs = srv.resolve("kk-page", lang="en")
        self.assertEqual(d["lang"], "en")

    def test_path_key_in_chaba_docs(self):
        self.fake.seed("api/x.md", coll="chaba-docs")
        coll, key, d, _ = srv.resolve("api/x.md")
        self.assertEqual(coll, "chaba-docs")

    def test_miss(self):
        self.assertEqual(srv.resolve("nope"), (None,) * 4)


class IndexRowsTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMDDB()
        self.orig_post, self.orig_listing = srv._post, srv.LISTING
        srv._post = self.fake.handle
        srv.LISTING = srv.ListingCache(ttl=60)
        self.now = dt.datetime.now(dt.timezone.utc)

    def tearDown(self):
        srv._post, srv.LISTING = self.orig_post, self.orig_listing

    def test_th_variant_dedup_and_status_filter(self):
        self.fake.seed("pg", meta_=meta(kind="page", slug="pg",
                                        domain="ops", status="active"))
        self.fake.seed("pg", lang="th", meta_=meta(kind="page", slug="pg",
                                                   status="active"))
        self.fake.seed("old", meta_=meta(kind="page", slug="old",
                                         status="superseded"))
        self.fake.seed("arc", meta_=meta(kind="archive", slug="arc",
                                         status="active"))
        rows = srv.index_rows("ada-cms-pages", self.now)
        slugs = [r["slug"] for r in rows]
        self.assertEqual(slugs, ["pg"])   # th dedup, superseded+archive out

    def test_sections(self):
        self.fake.seed("dg", meta_=meta(kind="page", slug="dg",
                                        report_role="digest", domain="news"))
        self.fake.seed("rp", meta_=meta(kind="report", slug="rp",
                                        domain="ops"))
        self.fake.seed("cam-1", meta_=meta(kind="page", slug="cam-1",
                                           domain="cctv"))
        rows = srv.index_rows("ada-cms-pages", self.now)
        secs = {r["slug"]: r["section"] for r in rows}
        self.assertEqual(secs, {"dg": "digests", "rp": "reports",
                                "cam-1": "cameras"})


class RouteTests(unittest.TestCase):
    """HTTP-level checks over FastAPI's TestClient with the fake MDDB."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.fake = FakeMDDB()
        cls.fake.seed("hello", meta_=meta(
            kind="page", slug="hello", domain="ops", status="active",
            title="Hello", summary="hi", updated="2026-10-15T00:00:00+00:00"),
            md="# Hello\n\nbody text")
        cls.fake.seed("news-digest", meta_=meta(
            kind="report", slug="news-digest", report_role="digest",
            domain="news", title="News digest",
            updated="2026-10-15T00:00:00+00:00"), md="# d")
        cls.orig_post = srv._post
        cls.orig_listing, cls.orig_pages, cls.orig_feeds = \
            srv.LISTING, srv.PAGES, srv.FEEDS
        srv._post = cls.fake.handle
        srv.LISTING = srv.ListingCache(ttl=600)
        srv.PAGES = srv.PageCache()
        srv.FEEDS = {}
        cls.client = TestClient(srv.app)

    @classmethod
    def tearDownClass(cls):
        srv._post = cls.orig_post
        srv.LISTING, srv.PAGES, srv.FEEDS = \
            cls.orig_listing, cls.orig_pages, cls.orig_feeds

    def test_healthz(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_index(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Hello", r.text)

    def test_page(self):
        r = self.client.get("/p/hello")
        self.assertEqual(r.status_code, 200)
        self.assertIn("body text", r.text)
        self.assertIn("Hello", r.text)

    def test_page_404(self):
        self.assertEqual(self.client.get("/p/ghost").status_code, 404)

    def test_kind_listing(self):
        r = self.client.get("/k/digest")
        self.assertEqual(r.status_code, 200)
        self.assertIn("news-digest", r.text)

    def test_feed(self):
        import xml.dom.minidom as md
        r = self.client.get("/feed/digest.xml")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/rss+xml", r.headers["content-type"])
        dom = md.parseString(r.text)
        self.assertEqual(len(dom.getElementsByTagName("item")), 1)


if __name__ == "__main__":
    unittest.main()
