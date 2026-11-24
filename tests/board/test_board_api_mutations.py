"""Unit tests for the unified mutation door endpoints on board-api
(card nest-api-unified-mutation-service): /lesson (WP lesson CPT upsert
+ auto-Thai), /job (nest_job CPT mirror of the ada-nest Drive queue),
/report (ada-cms-pages search/note/create) and /inbox (focus-inbox YAML).

Covers the seams the endpoints write through — wp_api, _gemini_thai,
_mddb_post, _crn — patched with fakes; no network, no WP, no MDDB, no
real repo writes (BOARD_API_COMMIT=0 + tmp INBOX_DIR).
"""

from __future__ import annotations

import base64
import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
                        "INBOX_DIR", "_th_cache", "_TH_CACHE_PATH",
                        "ATTACH_DIR")}
        self.tmp = Path(tempfile.mkdtemp())
        m.INBOX_DIR = self.tmp / "focus-inbox"
        m.INBOX_DIR.mkdir()
        # isolate the lesson-translation cache per test (KNB-1076)
        m._TH_CACHE_PATH = self.tmp / "lesson-th-cache.json"
        m._th_cache = {}

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
    def test_litellm_translation_key_uses_scoped_virtual_key(self):
        with patch.dict(os.environ, {"LITELLM_KEY_MDDB": ""}), \
                patch.object(self.mod, "_load_env_file",
                             side_effect=[
                                 {"LITELLM_KEY_MDDB": "mddb-virtual-key"}
                             ]):
            self.assertEqual(self.mod._litellm_translation_key(),
                             "mddb-virtual-key")

    def test_litellm_translation_key_supports_existing_mddb_env(self):
        with patch.dict(os.environ, {"LITELLM_KEY_MDDB": ""}), \
                patch.object(self.mod, "_load_env_file",
                             side_effect=[{}, {"LITELLM_KEY": "mddb-key"}]):
            self.assertEqual(self.mod._litellm_translation_key(), "mddb-key")

    def test_gemini_thai_uses_free_litellm_route(self):
        generate = Mock(return_value="<p>แปล</p>")
        with patch.object(self.mod, "_gemini_mod",
                          SimpleNamespace(generate=generate)), \
                patch.object(self.mod, "_litellm_translation_key",
                             return_value="virtual-md-db-key"), \
                patch.dict(os.environ,
                           {"BOARD_API_LITELLM_URL":
                            "http://gateway.test:4000"}):
            result = self.mod._gemini_thai("<p>English</p>")

        self.assertEqual(result, "<p>แปล</p>")
        args, kwargs = generate.call_args
        self.assertIn("<p>English</p>", args[0])
        self.assertEqual(args[1], "gemini-3.5-flash-lite-free")
        self.assertEqual(kwargs["key"], "virtual-md-db-key")
        self.assertEqual(kwargs["base_url_override"],
                         "http://gateway.test:4000")
        self.assertEqual(kwargs["max_attempts"], 1)

    def test_gemini_thai_caches_identical_content(self):
        """KNB-1076: re-filed lessons must not re-burn a translation
        call — sha256(content) hits the persisted cache."""
        generate = Mock(return_value="<p>แปล</p>")
        with patch.object(self.mod, "_gemini_mod",
                          SimpleNamespace(generate=generate)), \
                patch.object(self.mod, "_litellm_translation_key",
                             return_value="k"):
            first = self.mod._gemini_thai("<p>Same</p>")
            second = self.mod._gemini_thai("<p>Same</p>")
            other = self.mod._gemini_thai("<p>Different</p>")
        self.assertEqual(first, "<p>แปล</p>")
        self.assertEqual(second, "<p>แปล</p>")
        self.assertEqual(other, "<p>แปล</p>")
        self.assertEqual(generate.call_count, 2)  # cached hit skipped

    def test_gemini_thai_without_virtual_key_degrades_to_english(self):
        generate = Mock(return_value="<p>unexpected translation</p>")
        with patch.object(self.mod, "_gemini_mod",
                          SimpleNamespace(generate=generate)), \
                patch.object(self.mod, "_litellm_translation_key",
                             return_value=""):
            result = self.mod._gemini_thai("<p>English</p>")

        self.assertEqual(result, "")
        generate.assert_not_called()

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
             "evidence": ["ada-nest/packs/thonburian-bench/done"],
             "comms": "finished in 98s"}, "queue-mgr")
        self.assertEqual(res["action"], "created")
        route, payload = wp.posts[-1]
        self.assertEqual(route, "/wp/v2/nest_job")
        self.assertEqual(payload["slug"], "thonburian-bench")
        self.assertEqual(payload["status"], "private")
        self.assertEqual(payload["meta"]["status"], "done")
        self.assertEqual(payload["meta"]["host"], "colab-t4")
        self.assertEqual(payload["meta"]["evidence"],
                         "ada-nest/packs/thonburian-bench/done")
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

    # --- OPS-0923 lifecycle contract: transitions + terminal-done gate ---

    def _job_with_status(self, status, **meta):
        m = {"status": status}
        m.update(meta)
        return FakeWP([{"id": 7, "meta": m}])

    def test_done_requires_result_ref(self):
        wp = FakeWP()
        self.mod.wp_api = wp
        self.rejects(lambda: self.mod.do_job(
            {"slug": "s", "status": "done",
             "evidence": ["packs/s/done"]}, "queue-mgr"),
            "result_ref")
        self.assertEqual(wp.posts, [])          # rejected before any write

    def test_done_requires_verified_evidence(self):
        wp = FakeWP()
        self.mod.wp_api = wp
        # result_ref alone is a pointer, not proof — evidence required
        self.rejects(lambda: self.mod.do_job(
            {"slug": "s", "status": "done",
             "result_ref": "packs/s/done"}, "queue-mgr"),
            "verified artifact evidence")
        # evidence[] refs satisfy the gate and persist to meta
        res = self.mod.do_job(
            {"slug": "s", "status": "done",
             "result_ref": "packs/s/done",
             "evidence": ["packs/s/done", "packs/s/out.wav"]},
            "queue-mgr")
        self.assertEqual(res["action"], "created")
        meta = wp.posts[-1][1]["meta"]
        self.assertEqual(meta["status"], "done")
        self.assertIn("packs/s/out.wav", meta["evidence"])
        # verified:true is an equivalent honest signal
        wp.existing = [{"id": 9, "meta": {"status": "running"}}]
        res = self.mod.do_job(
            {"slug": "s2", "status": "done",
             "result_ref": "packs/s2/report.md", "verified": True},
            "queue-mgr")
        meta = wp.posts[-1][1]["meta"]
        self.assertEqual(meta["artifact_verified"], "true")
        # confidence=verified (publish path) also counts
        wp.existing = [{"id": 9, "meta": {"status": "running"}}]
        self.mod.do_job(
            {"slug": "s3", "status": "done",
             "result_ref": "packs/s3/x", "confidence": "verified"},
            "queue-mgr")
        self.assertEqual(wp.posts[-1][1]["meta"]["status"], "done")

    def test_done_gate_reads_existing_meta(self):
        # a post already carrying result_ref + artifact_verified passes
        # an idempotent done rewrite with no fresh evidence
        wp = self._job_with_status(
            "done", result_ref="packs/s/done", artifact_verified="true")
        self.mod.wp_api = wp
        res = self.mod.do_job({"slug": "s", "status": "done",
                               "note": "still done"}, "queue-mgr")
        self.assertEqual(res["action"], "updated")
        # but a legacy done post WITHOUT evidence cannot launder a
        # bare done rewrite — the gate inspects stored meta too
        wp = self._job_with_status("done", result_ref="packs/s/done")
        self.mod.wp_api = wp
        self.rejects(lambda: self.mod.do_job(
            {"slug": "s", "status": "done"}, "queue-mgr"),
            "verified artifact evidence")

    def test_invalid_transitions_rejected(self):
        wp = self._job_with_status("done")
        self.mod.wp_api = wp
        for bad in ("running", "claimed", "stalled", "cancelled"):
            self.rejects(lambda b=bad: self.mod.do_job(
                {"slug": "s", "status": b}, "queue-mgr"),
                "invalid transition")
        self.assertEqual(wp.posts, [])
        # cancelled is terminal the same way — only requeue/failed out
        wp = self._job_with_status("cancelled")
        self.mod.wp_api = wp
        self.rejects(lambda: self.mod.do_job(
            {"slug": "s", "status": "done",
             "result_ref": "x", "verified": True}, "queue-mgr"),
            "invalid transition")

    def test_terminal_requeue_and_failed_correction_allowed(self):
        # done -> queued is the honest requeue path
        wp = self._job_with_status("done")
        self.mod.wp_api = wp
        res = self.mod.do_job({"slug": "s", "status": "queued"},
                              "queue-mgr")
        self.assertEqual(res["action"], "updated")
        # done -> failed is the false-done correction (lost-artifact
        # class) — allowed, and failed is not terminal
        wp = self._job_with_status("done")
        self.mod.wp_api = wp
        res = self.mod.do_job({"slug": "s", "status": "failed",
                               "error": "artifact never landed"},
                              "queue-mgr")
        self.assertEqual(wp.posts[-1][1]["meta"]["status"], "failed")

    def test_failed_and_stalled_retries_allowed(self):
        # failed/stalled are retryable — any forward status is legal
        for prior in ("failed", "stalled"):
            for nxt in ("queued", "claimed", "running"):
                wp = self._job_with_status(prior)
                self.mod.wp_api = wp
                res = self.mod.do_job({"slug": "s", "status": nxt},
                                      "queue-mgr")
                self.assertEqual(res["action"], "updated",
                                 f"{prior} -> {nxt}")
        # stalled -> done still needs the evidence gate
        wp = self._job_with_status("stalled")
        self.mod.wp_api = wp
        self.rejects(lambda: self.mod.do_job(
            {"slug": "s", "status": "done"}, "queue-mgr"),
            "result_ref")

    def test_meta_status_cannot_bypass_gates(self):
        # meta.status rides the same JOB_META_KEYS merge — it must be
        # folded into the gated `status`, not smuggle a bare done past
        # the transition + evidence checks (OPS-0923 hardening)
        wp = self._job_with_status("running")
        self.mod.wp_api = wp
        self.rejects(lambda: self.mod.do_job(
            {"slug": "s", "meta": {"status": "done",
                                  "result_ref": "packs/s/done"}},
            "queue-mgr"), "verified artifact evidence")
        self.assertEqual(wp.posts, [])
        # ...and an illegal jump via meta.status is caught too
        wp = self._job_with_status("done")
        self.mod.wp_api = wp
        self.rejects(lambda: self.mod.do_job(
            {"slug": "s", "meta": {"status": "running"}},
            "queue-mgr"), "invalid transition")
        # a well-formed meta.status done still works (evidence inside
        # meta counts — _job_done_evidence reads body.meta)
        wp = self._job_with_status("running")
        self.mod.wp_api = wp
        res = self.mod.do_job(
            {"slug": "s", "meta": {"status": "done",
                                  "result_ref": "packs/s/done",
                                  "evidence": ["packs/s/done"]}},
            "queue-mgr")
        self.assertEqual(res["action"], "updated")
        self.assertEqual(wp.posts[-1][1]["meta"]["status"], "done")

    def test_conflicting_status_rejected(self):
        wp = self._job_with_status("running")
        self.mod.wp_api = wp
        self.rejects(lambda: self.mod.do_job(
            {"slug": "s", "status": "running",
             "meta": {"status": "done"}}, "queue-mgr"),
            "conflicting status")
        self.assertEqual(wp.posts, [])
        # bogus status hidden in meta is validated like top-level
        self.rejects(lambda: self.mod.do_job(
            {"slug": "s", "meta": {"status": "bogus"}}, "queue-mgr"),
            "status must be one of")

    def test_comms_only_write_ignores_transitions(self):
        # no status in the body = annotation, never a transition —
        # a done job can still take comms/meta updates
        wp = self._job_with_status("done")
        self.mod.wp_api = wp
        res = self.mod.do_job({"slug": "s", "note": "audited"},
                              "queue-mgr")
        self.assertEqual(res["action"], "updated")
        # prior status rides through untouched — no transition asserted
        self.assertEqual(wp.posts[-1][1]["meta"]["status"], "done")


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


class AttachDoorTest(DoorTestBase):
    """POST /attach (board-attachments-photo-image-evidence): file lands
    under ATTACH_DIR/<card-id>/, comms carries the canonical repo path,
    name collisions suffix -2, identical re-posts stay idempotent."""

    def setUp(self):
        super().setUp()
        self.mod.ATTACH_DIR = self.tmp / "attachments"
        self.card = {"id": "find-ups-replacement-batteries", "comms": []}
        self.png = base64.b64encode(b"\x89PNG\r\n\x1a\nfakedata").decode()

    def attach(self, **kw):
        body = {"filename": "ups-battery.png", "payload": self.png, **kw}
        return self.mod.do_attach(self.card, body, "tony")

    def test_validation(self):
        d = self.mod.do_attach
        self.rejects(lambda: d(self.card, {}, "tony"), "filename required")
        self.rejects(lambda: d(self.card, {"filename": "x.png"}, "tony"),
                     "payload")
        self.rejects(
            lambda: d(self.card,
                      {"filename": "x.png", "payload": "!!b64!!"}, "tony"),
            "base64")
        self.rejects(
            lambda: d(self.card,
                      {"filename": "evil.html", "payload": self.png}, "tony"),
            "must end with")
        self.rejects(
            lambda: d(self.card,
                      {"filename": "evil.svg", "payload": self.png}, "tony"),
            "must end with")
        self.rejects(
            lambda: d(self.card,
                      {"filename": "nope", "payload": self.png}, "tony"),
            "must end with")

    def test_stores_file_and_links_comms(self):
        msg, files, rel = self.attach()
        dest = self.mod.ATTACH_DIR / self.card["id"] / "ups-battery.png"
        self.assertEqual(files, [dest])
        self.assertTrue(dest.exists())
        self.assertEqual(
            rel, "docs/ssot/kanban/attachments/"
                 "find-ups-replacement-batteries/ups-battery.png")
        self.assertIn("attached ups-battery.png", msg)
        self.assertTrue(any(
            f"attachment: {rel}" in m["text"] and m["from"] == "tony"
            for m in self.card["comms"]))

    def test_filename_sanitized_and_traversal_killed(self):
        _, files, rel = self.attach(filename="../a b/UPS (1).JPG")
        self.assertEqual(files[0].parent.name, self.card["id"])
        self.assertNotIn("..", files[0].name)
        self.assertNotIn(" ", files[0].name)
        self.assertTrue(files[0].name.endswith(".JPG"))

    def test_data_uri_prefix_stripped(self):
        _, files, _ = self.attach(
            payload="data:image/png;base64," + self.png)
        self.assertEqual(files[0].read_bytes(),
                         base64.b64decode(self.png))

    def test_collision_suffix_and_idempotent_repost(self):
        _, f1, _ = self.attach()
        _, f2, _ = self.attach(payload=base64.b64encode(b"other").decode())
        self.assertEqual(f2[0].name, "ups-battery-2.png")
        _, f3, _ = self.attach()   # same name + same bytes -> idempotent
        self.assertEqual(f3[0], f1[0])
        self.assertEqual(
            len(list(self.mod.ATTACH_DIR.rglob("*.png"))), 2)


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
        self.assertEqual(payload["lang"], "en")
        self.assertEqual(payload["meta"]["lang"], ["en"])

    def test_create_lang_variant(self):
        """lang=de creates the German variant doc — the store keys
        variants by (collection, key, lang); any code passes through."""
        adds = []
        self.mod._mddb_post = (
            lambda p, payload, timeout=30: adds.append((p, payload)) or {})

        class FakeCRN:
            @staticmethod
            def merged_meta(doc, slug, now, today):
                return {"bank": ["cms"], "subject": [slug]}
        self.mod._crn = lambda: FakeCRN
        res = self.mod.do_report({"slug": "translate-probe", "lang": "de",
                                  "title": "Translate Probe (DE)",
                                  "content_md": "# hallo"}, "devin")
        self.assertEqual(res["slug"], "translate-probe")
        path, payload = adds[0]
        self.assertEqual(path, "add")
        self.assertEqual(payload["lang"], "de")
        self.assertEqual(payload["meta"]["lang"], ["de"])


if __name__ == "__main__":
    unittest.main()
