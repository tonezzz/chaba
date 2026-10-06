"""Unit tests for scripts/cam-wall/cam-wall-cms.py lifecycle handling —
supersede-by-construction, the 7-day archive retention pass, reports-index
exclusion, and the parseable fresh_for (card cms-cam-page-compaction).

Loads the dash-named script via importlib against a fully fake MDDB
transport — no network, no writes leave the test process.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/cam-wall/cam-wall-cms.py"

NOW = time.time()
DAY = 86400


class Resp:
    def __init__(self, payload, status=200):
        self._b = json.dumps(payload).encode()
        self.status = status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeMDDB:
    """In-process ada-cms-pages: /get /add /search; /delete is recorded
    so tests can assert the generator never deletes."""

    def __init__(self):
        self.docs = {}       # (key, lang) -> doc
        self.calls = []      # (path, body)

    def seed(self, key, lang="en", md="# x", meta=None, added=NOW):
        self.docs[(key, lang)] = {
            "id": f"ada-cms-pages|{key}|{lang}", "key": key, "lang": lang,
            "contentMd": md, "meta": meta or {},
            "addedAt": added, "updatedAt": added}

    def handle(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        body = {}
        if getattr(req, "data", None):
            body = json.loads(req.data)
        if url.endswith("/camwall"):
            return Resp({"zones": {}})
        path = url.rsplit("/", 1)[-1]
        if path == "get":
            d = self.docs.get((body["key"], body["lang"]))
            if d is None:
                raise urllib.error.HTTPError(url, 400, "not found", {}, None)
            return Resp(d)
        if path == "search":
            all_docs = sorted(self.docs.values(),
                              key=lambda d: (d["key"], d["lang"]))
            off = body.get("offset", 0)
            lim = body.get("limit", 500)
            return Resp(all_docs[off:off + lim])
        if path == "add":
            self.calls.append(("add", body))
            prev = self.docs.get((body["key"], body["lang"]))
            self.docs[(body["key"], body["lang"])] = {
                "id": f"ada-cms-pages|{body['key']}|{body['lang']}",
                "key": body["key"], "lang": body["lang"],
                "contentMd": body["contentMd"], "meta": body["meta"],
                "addedAt": (prev or {}).get("addedAt", NOW),
                "updatedAt": NOW}
            return Resp({"ok": True})
        if path == "delete":
            self.calls.append(("delete", body))
            return Resp({"ok": True})
        raise AssertionError(f"unexpected url {url}")


def _meta(status="active", kind="page", updated=None, **kw):
    m = {"kind": [kind], "status": [status], "generated_by": ["cam-wall-cms"],
         "slug": [], "updated": []}
    for k, v in kw.items():
        m[k] = v if isinstance(v, list) else [v]
    if updated:
        m["updated"] = [updated]
    return m


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(ts))


class CamWallCmsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data = Path(self.tmp.name)
        # zone vms-noble-a: two dev-keyed cams; zone rama9: one plain cam;
        # zone burapha: one Thai-keyed registry cam
        zones = {
            "vms-noble-a": [
                {"key": "guard-view", "label": "Guard View",
                 "dev": "noble-a", "ch": 2, "ok": True, "ts": NOW},
                {"key": "entrance-gate", "label": "4. Entrance Gate",
                 "dev": "noble-a", "ch": 4, "ok": True, "ts": NOW},
            ],
            "rama9": [{"key": "petchaburi-rd", "label": "Petchaburi Rd",
                       "ok": True, "ts": NOW}],
            "burapha": [{"key": "ทางพิเศษบูรพาวิถี----bangna-trat-km-0-east",
                         "label": "Trat km0 E", "ok": True, "ts": NOW}],
        }
        for z, cams in zones.items():
            zd = data / z
            zd.mkdir()
            (zd / f"manifest-{z}.json").write_text(json.dumps(
                {"updated": NOW, "cams": cams}))
        os.environ["CAMWALL_DATA"] = str(data)
        os.environ["MDDB_BASE_URL"] = "http://fake-mddb/v1"
        os.environ.pop("ADA_NOTIFY_KEY", None)

        spec = importlib.util.spec_from_file_location("cam_wall_cms", SCRIPT)
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["cam_wall_cms"] = self.mod
        spec.loader.exec_module(self.mod)

        self.db = FakeMDDB()
        self._patch = mock.patch.object(
            urllib.request, "urlopen", side_effect=self.db.handle)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def _seed_corpus(self):
        gen = {"generated_by": ["cam-wall-cms"]}
        # >7d orphan: renamed cam (cam01 -> entrance-gate)
        for lang in ("en", "th"):
            self.db.seed("cam-noble-a-cam01", lang,
                         meta=_meta(updated=_iso(NOW - 8 * DAY),
                                    sources=["zone:vms-noble-a"], **gen))
        # <7d orphan: zone-scoped key a dev-canonical slug replaced
        self.db.seed("cam-vms-noble-a-guard-view",
                     meta=_meta(updated=_iso(NOW - 1 * DAY),
                                sources=["zone:vms-noble-a"], **gen))
        # >7d orphan: retired wall-<zone> key form
        self.db.seed("wall-vms-noble-a",
                     meta=_meta(updated=_iso(NOW - 10 * DAY),
                                sources=["zone:vms-noble-a"], **gen))
        # >7d orphan: Thai raw slug the ascii slug replaced
        self.db.seed(
            "cam-burapha-ทางพ-เศษบ-รพาว-ถ----bangna-trat-km-0--east",
            meta=_meta(updated=_iso(NOW - 9 * DAY),
                       sources=["zone:burapha"], **gen))
        # >7d orphan: cam that left the roster entirely
        self.db.seed("cam-rama9-sukhumvit-soi-11",
                     meta=_meta(updated=_iso(NOW - 30 * DAY),
                                sources=["zone:rama9"], **gen))
        # foreign lane's zone — must be left alone
        self.db.seed("cam-vpslane-x",
                     meta=_meta(updated=_iso(NOW - 30 * DAY),
                                sources=["zone:vpslane"], **gen))
        # a page from another generator — must be left alone
        self.db.seed("cctv-roster-audit",
                     meta={"kind": ["page"], "status": ["active"],
                           "generated_by": ["cam-wall-roster-audit"]})
        # superseded page whose key is live again -> revive
        self.db.seed("cam-rama9-petchaburi-rd",
                     meta=_meta(status="superseded", kind="page",
                                superseded_by=["camwall-rama9"],
                                updated=_iso(NOW - 2 * DAY),
                                sources=["zone:rama9"], **gen))

    def test_full_lifecycle(self):
        self._seed_corpus()
        self.assertEqual(self.mod.main(), 0)
        g = lambda k, l="en": self.db.docs[(k, l)]["meta"]

        # 7d+ superseded pages flipped to kind:archive, never deleted
        for k in ("cam-noble-a-cam01", "wall-vms-noble-a",
                  "cam-burapha-ทางพ-เศษบ-รพาว-ถ----bangna-trat-km-0--east",
                  "cam-rama9-sukhumvit-soi-11"):
            self.assertEqual(g(k)["kind"], ["archive"], k)
            self.assertEqual(g(k)["status"], ["superseded"], k)
            self.assertIn("archived_at", g(k), k)
        self.assertEqual(g("cam-noble-a-cam01")["superseded_by"],
                         ["camwall-noble-a"])
        self.assertEqual(g("wall-vms-noble-a")["superseded_by"],
                         ["camwall-noble-a"])
        # thai raw slug resolves to its ascii successor
        self.assertEqual(
            g("cam-burapha-ทางพ-เศษบ-รพาว-ถ----bangna-trat-km-0--east")
            ["superseded_by"], ["cam-burapha-bangna-trat-km-0-east"])
        # nothing deleted — camera pages are operational history
        self.assertFalse([c for c in self.db.calls if c[0] == "delete"])

        # <7d superseded page keeps kind:page inside the grace window
        self.assertEqual(g("cam-vms-noble-a-guard-view")["status"],
                         ["superseded"])
        self.assertEqual(g("cam-vms-noble-a-guard-view")["kind"], ["page"])
        self.assertEqual(g("cam-vms-noble-a-guard-view")["superseded_by"],
                         ["cam-noble-a-guard-view"])

        # foreign-lane + other-generator docs untouched
        self.assertEqual(g("cam-vpslane-x")["status"], ["active"])
        self.assertEqual(g("cctv-roster-audit")["status"], ["active"])

        # new canonical pages carry supersedes + parseable fresh_for
        self.assertEqual(g("cam-noble-a-guard-view")["supersedes"],
                         ["cam-vms-noble-a-guard-view"])
        self.assertEqual(g("cam-burapha-bangna-trat-km-0-east")
                         ["supersedes"],
                         ["cam-burapha-ทางพ-เศษบ-รพาว-ถ----"
                          "bangna-trat-km-0--east"])
        self.assertEqual(g("camwall-noble-a")["fresh_for"], ["1h"])

        # revive: back in the publish set -> active, markers stripped
        self.assertEqual(g("cam-rama9-petchaburi-rd")["status"], ["active"])
        self.assertEqual(g("cam-rama9-petchaburi-rd")["kind"], ["page"])
        self.assertNotIn("superseded_by", g("cam-rama9-petchaburi-rd"))

        # reports-index was regenerated and excludes superseded/archived
        idx = self.db.docs[("reports-index", "en")]["contentMd"]
        self.assertIn("cam-rama9-petchaburi-rd", idx)
        for gone in ("cam-noble-a-cam01", "wall-vms-noble-a",
                     "cam-vms-noble-a-guard-view",
                     "cam-rama9-sukhumvit-soi-11"):
            self.assertNotIn(gone, idx)

        # count check: live cam-* keys == the manifest's canonical set
        live_cam = {k for (k, l) in self.db.docs
                    if k.startswith(("cam-", "camwall-"))
                    and (self.db.docs[(k, l)]["meta"].get("status")
                         or [""])[0] == "active"}
        self.assertEqual(live_cam, {
            "cam-noble-a-guard-view", "cam-noble-a-entrance-gate",
            "cam-rama9-petchaburi-rd", "cam-burapha-bangna-trat-km-0-east",
            "camwall-noble-a", "camwall-rama9", "camwall-burapha",
            "cam-vpslane-x"})  # foreign lane's doc stays active

    def test_empty_zones_marks_nothing(self):
        """All manifests gone -> nothing is superseded (can't know the
        intended state)."""
        import shutil
        for d in Path(os.environ["CAMWALL_DATA"]).iterdir():
            if d.is_dir():
                shutil.rmtree(d)
        self.db.seed("cam-noble-a-cam01",
                     meta=_meta(updated=_iso(NOW - 30 * DAY),
                                sources=["zone:vms-noble-a"]))
        self.assertEqual(self.mod.main(), 0)
        self.assertEqual(
            self.db.docs[("cam-noble-a-cam01", "en")]["meta"]["status"],
            ["active"])


class IndexLibTest(unittest.TestCase):
    """scripts/lib/cms_index.py — the shared reports-index render."""

    def test_excludes_and_stale_flag(self):
        sys.path.insert(0, str(REPO / "scripts"))
        from lib import cms_index
        now = _dt.datetime.now(_dt.timezone.utc)
        docs = [
            {"key": "a", "meta": {"kind": ["page"], "status": ["active"],
                                  "slug": ["a"], "updated": [
                                      now.isoformat()],
                                  "fresh_for": ["1h"], "summary": ["ok"]}},
            {"key": "b", "meta": {"kind": ["page"],
                                  "status": ["superseded"],
                                  "slug": ["b"], "updated": [
                                      now.isoformat()]}},
            {"key": "c", "meta": {"kind": ["archive"],
                                  "status": ["superseded"],
                                  "slug": ["c"], "updated": [
                                      now.isoformat()]}},
            {"key": "d", "meta": {"kind": ["page"], "status": ["active"],
                                  "slug": ["d"], "fresh_for": ["1h"],
                                  "updated": [
                                      (now - _dt.timedelta(hours=2))
                                      .isoformat()]}},
        ]
        rows = cms_index.index_rows(docs, now)
        slugs = [r["slug"] for r in rows]
        self.assertEqual(sorted(slugs), ["a", "d"])
        self.assertTrue(next(r for r in rows if r["slug"] == "d")["stale"])
        self.assertFalse(next(r for r in rows if r["slug"] == "a")["stale"])
        # the old "600" form never evaluated — documents why it changed
        self.assertFalse(cms_index.stale(
            {"fresh_for": ["600"], "updated": [
                (now - _dt.timedelta(days=30)).isoformat()]}, now))


if __name__ == "__main__":
    unittest.main()
