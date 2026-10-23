"""Unit tests for the unified mutation door endpoints on board-api
(card nest-api-unified-mutation-service): /lesson (WP lesson CPT upsert
+ auto-Thai), /job (nest_job CPT mirror of the ada-nest Drive queue),
/report (ada-cms-pages search/note/create) and /inbox (focus-inbox YAML).

Covers the seams the endpoints write through — wp_api, _gemini_thai,
_mddb_post, _crn — patched with fakes; no network, no WP, no MDDB, no
real repo writes (BOARD_API_COMMIT=0 + tmp INBOX_DIR).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

os.environ["BOARD_API_COMMIT"] = "0"  # tmp dirs aren't repo files

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / "board" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeWP:
    """Records POSTs; returns `existing` for any slug-lookup GET."""

    def __init__(self, existing=None):
        self.existing = existing or []
        self.posts = []

    def __call__(self, route, data=None):
        if data is None:
            return self.existing
        self.posts.append((route, data))
        return {"id": 42}


class DoorTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load("board-api.py")

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in
                       ("wp_api", "_gemini_thai", "_mddb_post", "_crn",
                        "INBOX_DIR")}
        self.tmp = Path(tempfile.mkdtemp())
        m.INBOX_DIR = self.tmp / "focus-inbox"
        m.INBOX_DIR.mkdir()

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.mod, k, v)

    def rejects(self, fn, frag):
        try:
            fn()
        except ValueError as e:
            self.assertIn(frag, str(e))
            return
        raise AssertionError(f"expected ValueError containing {frag!r}")


class LessonDoorTest(DoorTestBase):
    def test_validation(self):
        d = self.mod.do_lesson
        self.rejects(lambda: d({}, "devin"), "topic required")
        self.rejects(lambda: d({"topic": "t"}, "devin"),
                     "content required")
        self.rejects(lambda: d({"topic": "t", "content": "x",
                                "level": "phd"}, "devin"),
                     "level must be one of")
        self.rejects(lambda: d({"topic": "t", "content": "x",
                                "source": "smoke"}, "devin"),
                     "source must be one of")

    def test_create_with_thai(self):
        wp = FakeWP()
        self.mod.wp_api = wp
        self.mod._gemini_thai = lambda h: "<p>แปล</p>"
        res = self.mod.do_lesson(
            {"topic": "Object Storage", "content": "<p>hi</p>",
             "level": "working", "source": "voice"}, "devin")
        self.assertEqual(res["action"], "created")
        self.assertTrue(res["th"])
        route, payload = wp.posts[-1]
        self.assertEqual(route, "/wp/v2/lesson")
        self.assertTrue(payload["slug"].startswith("lesson-"))
        self.assertIn("ไทย", payload["content"])
        self.assertEqual(payload["status"], "private")
        meta = payload["meta"]
        self.assertEqual(meta["topic"], "Object Storage")
        self.assertEqual(meta["level"], "working")
        self.assertEqual(meta["source"], "voice")
        today = dt.date.today()
        self.assertEqual(meta["next_review"],
                         str(today + dt.timedelta(days=7)))

    def test_update_preserves_provenance(self):
        wp = FakeWP([{"id": 42, "meta": {"learned_at": "2026-01-01",
                                         "next_review": "2026-01-08",
                                         "status": "learned"}}])
        self.mod.wp_api = wp
        self.mod._gemini_thai = lambda h: ""
        res = self.mod.do_lesson({"topic": "Object Storage",
                                  "content": "<p>v2</p>"}, "devin")
        self.assertEqual(res["action"], "updated")
        self.assertFalse(res["th"])
        route, payload = wp.posts[-1]
        self.assertEqual(route, "/wp/v2/lesson/42")
        self.assertEqual(payload["meta"]["learned_at"], "2026-01-01")
        self.assertEqual(payload["meta"]["next_review"], "2026-01-08")
        self.assertEqual(payload["meta"]["status"], "learned")

    def test_thai_failure_degrades_to_en(self):
        wp = FakeWP()
        self.mod.wp_api = wp
        self.mod._gemini_thai = lambda h: ""
        res = self.mod.do_lesson({"topic": "t", "content": "<p>x</p>"},
                                 "devin")
        self.assertFalse(res["th"])
        self.assertNotIn("ไทย", wp.posts[-1][1]["content"])


class JobDoorTest(DoorTestBase):
    def test_actor(self):
        j = self.mod.job_actor
        self.assertEqual(j({}, "local"), "local")
        self.assertEqual(j({"from": "queue-mgr"}, "local"), "queue-mgr")
        self.assertEqual(j({"from": "tony-dell"}, "x"), "tony-dell")
        self.assertEqual(j({"from": "ada"}, "x"), "ada")
        self.rejects(lambda: j({"from": "Bad Name!"}, "x"),
                     "from must be")

    def test_validation(self):
        d = self.mod.do_job
        self.mod.wp_api = FakeWP()
        self.rejects(lambda: d({}, "queue-mgr"), "slug must match")
        self.rejects(lambda: d({"slug": "Bad_Slug"}, "queue-mgr"),
                     "slug must match")
        self.rejects(lambda: d({"slug": "s", "status": "weird"},
                               "queue-mgr"), "status must be one of")
        self.rejects(lambda: d({"slug": "s", "parent": "nope"},
                               "queue-mgr"), "no parent job")

    def test_create_and_update(self):
        wp = FakeWP()
        self.mod.wp_api = wp
        res = self.mod.do_job(
            {"slug": "thonburian-bench", "status": "done", "kind": "pack",
             "pack": "thonburian-bench", "host": "colab-t4",
             "result_ref": "ada-nest/packs/thonburian-bench",
             "comms": "finished in 98s"}, "queue-mgr")
        self.assertEqual(res["action"], "created")
        route, payload = wp.posts[-1]
        self.assertEqual(route, "/wp/v2/nest_job")
        self.assertEqual(payload["slug"], "thonburian-bench")
        self.assertEqual(payload["status"], "private")
        self.assertEqual(payload["meta"]["status"], "done")
        self.assertEqual(payload["meta"]["host"], "colab-t4")
        log = json.loads(payload["meta"]["comms"])
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["from"], "queue-mgr")
        self.assertIn("98s", log[0]["text"])

        # second write: upsert same slug, comms appends not replaces
        wp.existing = [{"id": 7, "meta": {"comms": payload["meta"]["comms"]}}]
        res = self.mod.do_job({"slug": "thonburian-bench",
                               "status": "failed", "note": "died"}, "dell")
        self.assertEqual(res["action"], "updated")
        route, payload = wp.posts[-1]
        self.assertEqual(route, "/wp/v2/nest_job/7")
        log = json.loads(payload["meta"]["comms"])
        self.assertEqual(len(log), 2)
        self.assertIn("98s", log[0]["text"])
        self.assertEqual(log[1]["from"], "dell")

    def test_comms_json_heal_and_parent(self):
        wp = FakeWP([{"id": 7, "meta": {"comms": "not json"}}])
        self.mod.wp_api = wp
        self.mod.do_job({"slug": "s", "note": "recovered"}, "queue-mgr")
        log = json.loads(wp.posts[-1][1]["meta"]["comms"])
        self.assertEqual(len(log), 1)
        # parent slug resolves to its post id
        wp.existing = [{"id": 7, "meta": {}}]
        self.mod.do_job({"slug": "child", "parent": 7}, "queue-mgr")
        self.assertEqual(wp.posts[-1][1]["parent"], 7)

    def test_meta_allowlist(self):
        wp = FakeWP()
        self.mod.wp_api = wp
        self.mod.do_job({"slug": "s", "status": "queued",
                         "meta": {"host": "mn01", "bogus": "drop"}},
                        "queue-mgr")
        meta = wp.posts[-1][1]["meta"]
        self.assertEqual(meta["host"], "mn01")
        self.assertNotIn("bogus", meta)


class InboxDoorTest(DoorTestBase):
    def test_write_and_shape(self):
        res = self.mod.do_inbox(
            {"text": "Try the new sweep cadence", "label": "Sweep cadence",
             "tags": ["ops"], "priority": "high",
             "missing_info": ["what cadence?"],
             "session": "abc-123"}, "ada")
        fp = self.mod.INBOX_DIR / res["file"]
        self.assertTrue(fp.exists())
        self.assertTrue(res["file"].endswith("-sweep-cadence.yml"))
        doc = yaml.safe_load(fp.read_text())
        self.assertEqual(doc["focus"]["label"], "Sweep cadence")
        self.assertEqual(doc["focus"]["priority"], "high")
        self.assertEqual(doc["focus"]["status"], "draft")
        self.assertEqual(doc["focus"]["tags"], ["ops"])
        self.assertEqual(doc["focus"]["missing_info"], ["what cadence?"])
        self.assertEqual(doc["ownership"]["owner"], "tony")
        self.assertEqual(doc["source"]["session"], "abc-123")

    def test_label_defaults_from_text(self):
        res = self.mod.do_inbox(
            {"text": "just a quick thought about things"}, "devin")
        doc = yaml.safe_load(
            (self.mod.INBOX_DIR / res["file"]).read_text())
        self.assertTrue(doc["focus"]["label"])

    def test_validation(self):
        d = self.mod.do_inbox
        self.rejects(lambda: d({}, "ada"), "text required")
        self.rejects(lambda: d({"text": "x", "priority": "urgent"}, "ada"),
                     "priority must be")
        self.rejects(lambda: d({"text": "x", "tags": "ops"}, "ada"),
                     "tags must be a list")


class ReportDoorTest(DoorTestBase):
    def test_mode_inference_and_validation(self):
        d = self.mod.do_report
        self.rejects(lambda: d({}, "devin"), "report needs")
        self.rejects(lambda: d({"mode": "bogus"}, "devin"),
                     "mode must be")
        self.rejects(lambda: d({"slug": "Bad!", "note": "x"}, "devin"),
                     "slug must match")
        self.rejects(lambda: d({"slug": "ok-slug"}, "devin"),
                     "report needs")
        self.rejects(lambda: d({"mode": "search"}, "devin"),
                     "search needs query")

    def test_title_alone_infers_search(self):
        self.mod._mddb_post = lambda p, payload, timeout=30: []
        res = self.mod.do_report({"title": "kanban"}, "devin")
        self.assertEqual(res["candidates"], [])

    def test_search(self):
        self.mod._mddb_post = lambda p, payload, timeout=30: [
            {"key": "dev-kanban",
             "meta": {"title": ["Dev kanban"], "updated": ["u"]}}]
        res = self.mod.do_report({"query": "kanban"}, "devin")
        self.assertEqual(len(res["candidates"]), 1)
        self.assertEqual(res["candidates"][0]["slug"], "dev-kanban")
        self.assertEqual(res["candidates"][0]["title"], "Dev kanban")

    def test_note(self):
        class FakeCRN:
            @staticmethod
            def note(slug, text, lang):
                return {"slug": slug, "line": f"* t — {text}",
                        "updated": "u"}
        self.mod._crn = lambda: FakeCRN
        res = self.mod.do_report({"slug": "dev-kanban", "note": "prog"},
                                 "devin")
        self.assertIn("noted dev-kanban", res["message"])

    def test_create(self):
        adds = []
        self.mod._mddb_post = (
            lambda p, payload, timeout=30: adds.append((p, payload)) or {})

        class FakeCRN:
            @staticmethod
            def merged_meta(doc, slug, now, today):
                return {"bank": ["cms"], "subject": [slug]}
        self.mod._crn = lambda: FakeCRN
        res = self.mod.do_report({"title": "New Report",
                                  "content_md": "# hi"}, "devin")
        self.assertEqual(res["slug"], "new-report")
        path, payload = adds[0]
        self.assertEqual(path, "add")
        self.assertEqual(payload["collection"], "ada-cms-pages")
        self.assertEqual(payload["key"], "new-report")
        self.assertEqual(payload["meta"]["subject"], ["new-report"])


if __name__ == "__main__":
    unittest.main()
