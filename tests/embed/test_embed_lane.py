"""Unit tests for the embed-lane store + the news-digest cache path
(card embedding-backfill-lanes). Pure functions only — no network, no
litellm, no WP. Guards the byte-level contract between the two sides:
a vector written by embed-lane must hit in news-digest's cache lookup,
and the space pin must reject foreign-space rows.
"""
import base64
import hashlib
import importlib.util
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


el = load("embed_lane", "scripts/embed/embed-lane.py")
nd = load("news_digest", "scripts/ada/news-digest.py")


def vec(seed):
    return [float(seed + i) / 100.0 for i in range(768)]


class TestVectors(unittest.TestCase):
    def test_b64_roundtrip(self):
        v = vec(1)
        for a, b in zip(el.b64d(el.b64e(v)), v):
            self.assertAlmostEqual(a, b, places=6)
        for a, b in zip(nd._b64d(nd._b64e(v)), v):
            self.assertAlmostEqual(a, b, places=6)

    def test_norm_matches_digest(self):
        """embed-lane.norm must byte-match news-digest.norm — the cache
        key is sha1(norm(title)); any drift silently zeroes hit rate."""
        for t in ["A  Flood <b>Update</b> — Now", "เรื่อง ใหญ่ &amp; เล็ก",
                  "  spaced   out  "]:
            self.assertEqual(el.norm(t), nd.norm(t))

    def test_hash_contract(self):
        """embed-lane stores sha1(unprefixed text)[:16]; the digest
        looks the row up by the same digest."""
        t = nd.norm("Some Title Here")
        self.assertEqual(el.sha(t), nd._thash(t))


class TestChunking(unittest.TestCase):
    def test_chunk_bounds(self):
        text = "\n\n".join(f"paragraph {i} " + "x" * 600 for i in range(6))
        chunks = el.chunk_text("Title", text, size=1500)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= 1510 for c in chunks))
        self.assertTrue(chunks[0].startswith("Title"))
        self.assertTrue(all(len(c) > 20 for c in chunks))

    def test_empty(self):
        self.assertEqual(el.chunk_text("T", ""), [])


class TestStoreCacheContract(unittest.TestCase):
    def test_digest_reads_lane_store(self):
        """Rows appended by embed_into_store must surface in
        news-digest._embed_cache keyed by title hash; foreign-space
        rows must be ignored."""
        with tempfile.TemporaryDirectory() as d:
            store = os.path.join(d, "news-nomic.jsonl")
            title = nd.norm("Cache Contract Title")
            row = {"key": "n-abc", "space": "nomic-embed-text",
                   "model": "ollama-nomic-embed", "prefix": "",
                   "hash": hashlib.sha1(title.encode()).hexdigest()[:16],
                   "text": title, "meta": {}, "v": el.b64e(vec(2))}
            foreign = dict(row, key="n-other", space="bge-m3",
                           hash="0" * 16)
            with open(store, "w") as f:
                f.write(json.dumps(row) + "\n")
                f.write(json.dumps(foreign) + "\n")
            os.environ["NEWS_VEC_CACHE"] = store
            try:
                cache = nd._embed_cache()
            finally:
                os.environ.pop("NEWS_VEC_CACHE")
            self.assertIn(row["hash"], cache)
            self.assertNotIn("0" * 16, cache)
            for a, b in zip(nd._b64d(cache[row["hash"]]), vec(2)):
                self.assertAlmostEqual(a, b, places=6)

    def test_resume_skips_unchanged(self):
        """load_hashes dedups on (key, hash): an unchanged doc is not
        re-embedded; a changed hash re-embeds."""
        with tempfile.TemporaryDirectory() as d:
            store = os.path.join(d, "s.jsonl")
            el.append_rows(store, [{"key": "k1", "hash": el.sha("v1"),
                                    "v": el.b64e(vec(3))}])
            self.assertEqual(el.load_hashes(store)["k1"], el.sha("v1"))
            self.assertNotEqual(el.load_hashes(store)["k1"], el.sha("v2"))


class TestDocsPagination(unittest.TestCase):
    """_docs must page /v1/search by offset until a short page — the
    server caps a page at PAGE docs regardless of the requested limit,
    so a single big-limit call silently truncated collections >1000
    (card embed-lane-banks-search-pagination)."""

    def _fake_search(self, pages, wrap=None):
        """pages: {offset: [docs]} — returns a _post stand-in that
        serves {offset} slices and records every request payload."""
        calls = []

        def fake_post(url, payload, timeout=60, headers=None):
            calls.append(payload)
            self.assertEqual(payload["limit"], el.PAGE)
            page = pages(payload["offset"])
            return wrap(page) if wrap else page
        return calls, fake_post

    def _docs_page(self, start, n):
        return [{"key": f"k-{i}"} for i in range(start, start + n)]

    def test_paginates_until_short_page(self):
        sizes = {0: 1000, 1000: 1000, 2000: 137}
        calls, fake = self._fake_search(
            lambda off: self._docs_page(off, sizes.get(off, 0)))
        with mock.patch.object(el, "_post", fake), \
                mock.patch.object(el.time, "sleep"):
            docs = el._docs("http://x", "coll", True)
        self.assertEqual([c["offset"] for c in calls], [0, 1000, 2000])
        self.assertTrue(all(c["include_content"] for c in calls))
        self.assertEqual(len(docs), 2137)
        self.assertEqual({d["key"] for d in docs},
                         {f"k-{i}" for i in range(2137)})

    def test_short_first_page_no_second_request(self):
        calls, fake = self._fake_search(
            lambda off: self._docs_page(off, 300 if off == 0 else 0))
        with mock.patch.object(el, "_post", fake), \
                mock.patch.object(el.time, "sleep"):
            docs = el._docs("http://x", "coll", False)
        self.assertEqual([c["offset"] for c in calls], [0])
        self.assertEqual(len(docs), 300)

    def test_exact_page_boundary_stops_on_empty(self):
        calls, fake = self._fake_search(
            lambda off: self._docs_page(off, el.PAGE)
            if off < 2 * el.PAGE else [])
        with mock.patch.object(el, "_post", fake), \
                mock.patch.object(el.time, "sleep"):
            docs = el._docs("http://x", "coll", False)
        self.assertEqual([c["offset"] for c in calls],
                         [0, el.PAGE, 2 * el.PAGE])
        self.assertEqual(len(docs), 2 * el.PAGE)

    def test_offset_ignored_server_does_not_spin(self):
        """A server that ignores offset returns the same full page
        forever — the all-keys-seen guard must break the loop."""
        calls, fake = self._fake_search(
            lambda off: self._docs_page(0, el.PAGE))
        with mock.patch.object(el, "_post", fake), \
                mock.patch.object(el.time, "sleep"):
            docs = el._docs("http://x", "coll", False)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(docs), el.PAGE)

    def test_dict_wrapped_results_page(self):
        calls, fake = self._fake_search(
            lambda off: self._docs_page(off, 40 if off == 0 else 0),
            wrap=lambda page: {"results": page})
        with mock.patch.object(el, "_post", fake), \
                mock.patch.object(el.time, "sleep"):
            docs = el._docs("http://x", "coll", False)
        self.assertEqual(len(docs), 40)


class TestBanksCursor(unittest.TestCase):
    """cmd_banks resumable slices (card embed-lane-banks-incremental-
    copy-fix): per-bank offset cursor + persisted have-set mean each
    run copies a bounded slice and the next resumes — no re-scan, no
    dup adds, exit 0 on budget/cap, non-zero on real errors."""

    def _env(self, ndocs=6, coll="c1", page=None):
        src = {f"k{i}": {"key": f"k{i}", "lang": "en",
                        "contentMd": f"body {i}", "meta": {}}
               for i in range(ndocs)}
        target = {}
        reqs = []

        def fake_post(url, payload, timeout=60, headers=None):
            if url.endswith("/v1/search"):
                reqs.append((":11028" in url, payload["offset"]))
                off, lim = payload["offset"], payload["limit"]
                if ":11028" in url:
                    docs = list(target.values())
                else:
                    docs = list(src.values()) if payload["collection"] == coll else []
                return docs[off:off + lim]
            if url.endswith("/v1/add"):
                target[payload["key"]] = payload
                return {"ok": True}
            if url.endswith("/v1/vector-stats"):
                return {"queue": {"depth": 0, "dropped": 0}}
            raise AssertionError(url)

        def run(d, **kw):
            args = mock.Mock(collection=["c1" if coll == "c1" else coll],
                             dir=d, dry_run=False, force=False, budget=0,
                             max_docs=0, limit=0, queue_hi=3000,
                             rescan_hours=6.0, have_refresh=24)
            for k, v in kw.items():
                setattr(args, k, v)
            with mock.patch.object(el, "_post", fake_post), \
                    mock.patch.object(el, "PAGE", page or el.PAGE), \
                    mock.patch.object(el.time, "sleep"):
                return el.cmd_banks(args, None, None)
        return run, target, reqs

    def _state(self, d, coll="c1"):
        return json.load(open(os.path.join(
            d, "banks-state.json")))["collections"][coll]

    def test_bounded_runs_resume_and_converge(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            run, target, _ = self._env(ndocs=6, page=2)
            # three capped runs of 2 docs each — offset must advance
            offs = []
            for _ in range(3):
                self.assertEqual(run(d, max_docs=2), 0)
                offs.append(self._state(d)["offset"])
            self.assertEqual(offs, [2, 4, 6])
            self.assertEqual(len(target), 6)
            # fourth run sees the short/empty tail and closes the pass
            self.assertEqual(run(d, max_docs=2), 0)
            st = self._state(d)
            self.assertEqual(st["pass"], 1)
            self.assertEqual(st["src_total"], 6)
            self.assertTrue(st["synced_at"])
            # synced bank skips — zero new /v1/add calls
            n_add = len(target)
            self.assertEqual(run(d), 0)
            self.assertEqual(len(target), n_add)

    def test_resume_does_not_rescan_or_duplicate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            run, target, reqs = self._env(ndocs=6, page=2)
            run(d, max_docs=2)
            reqs.clear()
            run(d, max_docs=2)
            src_offs = [o for is_t, o in reqs if not is_t]
            # resumed at the persisted cursor — never re-requests row 0
            self.assertNotIn(0, src_offs)
            self.assertEqual(sorted(target), [f"k{i}" for i in range(4)])

    def test_all_add_failures_exit_nonzero(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            run, target, _ = self._env(ndocs=2, page=2)

            def boom(url, payload, timeout=60, headers=None):
                if url.endswith("/v1/add"):
                    raise RuntimeError("target down")
                if url.endswith("/v1/search"):
                    off, lim = payload["offset"], payload["limit"]
                    docs = ([] if ":11028" in url else
                            [{"key": f"k{i}", "lang": "en",
                              "contentMd": "x", "meta": {}}
                             for i in range(2)])
                    return docs[off:off + lim]
                if url.endswith("/v1/vector-stats"):
                    return {"queue": {"depth": 0, "dropped": 0}}
                raise AssertionError(url)
            args = mock.Mock(collection=["c1"], dir=d, dry_run=False,
                             force=False, budget=0, max_docs=0, limit=0,
                             queue_hi=3000, rescan_hours=6.0,
                             have_refresh=24)
            with mock.patch.object(el, "_post", boom), \
                    mock.patch.object(el, "PAGE", 2), \
                    mock.patch.object(el.time, "sleep"):
                rc = el.cmd_banks(args, None, None)
            self.assertEqual(rc, 1)
            self.assertEqual(target, {})

    def test_transient_scan_errors_eventually_alert(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            def down_src(url, payload, timeout=60, headers=None):
                if url.endswith("/v1/search"):
                    if ":11028" in url:
                        return []          # empty target have-set
                    raise RuntimeError("Remote end closed connection")
                if url.endswith("/v1/vector-stats"):
                    return {"queue": {"depth": 0, "dropped": 0}}
                raise AssertionError(url)
            args = mock.Mock(collection=["c1"], dir=d, dry_run=False,
                             force=False, budget=0, max_docs=0, limit=0,
                             queue_hi=3000, rescan_hours=6.0,
                             have_refresh=24)
            rcs = []
            for _ in range(el.SCAN_FAIL_ALERT):
                with mock.patch.object(el, "_post", down_src), \
                        mock.patch.object(el, "PAGE", 2), \
                        mock.patch.object(el.time, "sleep"):
                    rcs.append(el.cmd_banks(args, None, None))
            # single blips stay rc=0; the run fails only once the same
            # collection has errored SCAN_FAIL_ALERT times consecutively
            self.assertEqual(rcs, [0] * (el.SCAN_FAIL_ALERT - 1) + [1])


if __name__ == "__main__":
    unittest.main()
