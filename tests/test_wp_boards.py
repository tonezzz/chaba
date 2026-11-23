"""Unit tests for scripts/lib/wp_boards.py + scripts/ada/render-job-record.py
— the render_job media-upload writer (card
render-job-writer-must-upload-output-to-78229c).

Fully offline: urllib.request.urlopen is mocked with an in-process fake WP
(/wp/v2/media + /wp/v2/render_job) — no network, no writes leave the test
process. Pins the card's contract: output binary is POSTed to /wp/v2/media
first, the render_job post's output_url meta is the returned source_url
(never a filesystem path), featured_media carries the attachment id, and a
path-shaped output_url is rejected outright.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

spec = importlib.util.spec_from_file_location(
    "wp_boards", REPO / "scripts" / "lib" / "wp_boards.py")
wpb = importlib.util.module_from_spec(spec)
sys.modules["wp_boards"] = wpb
spec.loader.exec_module(wpb)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


class Resp:
    def __init__(self, payload, status=200, raw=None):
        self._b = raw if raw is not None else json.dumps(payload).encode()
        self.status = status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeWP:
    """Minimal /wp/v2 media + render_job store."""

    def __init__(self):
        self.media = {}
        self.posts = {}
        self.next_id = 500
        self.calls = []

    def handle(self, req, timeout=None):
        url = req.full_url
        method = req.get_method()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        route = qs["rest_route"][0]
        self.calls.append((method, route))
        body = json.loads(req.data) if req.data and \
            "json" in (req.headers.get("Content-type") or "") else None

        if route == "/wp/v2/media" and method == "POST":
            mid = self.next_id
            self.next_id += 1
            self.media[mid] = {"bytes": req.data,
                               "filename": req.headers.get(
                                   "Content-disposition", "")}
            return Resp({"id": mid,
                         "source_url": f"https://wp/uploads/{mid}.png"},
                        201)
        if route.startswith("/wp/v2/render_job") and method == "GET":
            slug = (qs.get("slug") or [""])[0]
            return Resp([p for p in self.posts.values()
                         if p.get("slug") == slug])
        if route == "/wp/v2/render_job" and method == "POST":
            pid = self.next_id
            self.next_id += 1
            rec = dict(body)
            rec["id"] = pid
            self.posts[pid] = rec
            return Resp(dict(rec), 201)
        if route.startswith("/wp/v2/render_job/") and method == "POST":
            pid = int(route.rsplit("/", 1)[1])
            self.posts[pid].update(body)
            return Resp(dict(self.posts[pid]))
        raise AssertionError(f"unexpected {method} {route}")


class WPBoardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = Path(self.tmp.name) / "wp-boards.env"
        env.write_text("WP_SITE_URL=https://fake-wp\n"
                       "WP_APP_USER=agent\nWP_APP_PASSWORD=pw\n")
        self.wp = wpb.WpBoards(env_path=str(env))
        self.net = FakeWP()
        self._patch = mock.patch.object(
            urllib.request, "urlopen", side_effect=self.net.handle)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def _png(self):
        p = Path(self.tmp.name) / "test-sdxl-1024.png"
        p.write_bytes(PNG)
        return p

    def test_upload_media_returns_source_url(self):
        att = self.wp.upload_media(self._png())
        self.assertEqual(att["id"], 500)
        self.assertEqual(att["source_url"], "https://wp/uploads/500.png")
        self.assertEqual(self.net.media[500]["bytes"], PNG)

    def test_write_render_job_uploads_then_records(self):
        res = self.wp.write_render_job(
            kind="image", prompt="a cat on a surfboard", output=self._png(),
            meta={"model": "sdxl-lightning", "steps": "4"})
        # upload happened BEFORE the post create
        self.assertEqual(self.net.calls[0][1], "/wp/v2/media")
        self.assertEqual(self.net.calls[1][1], "/wp/v2/render_job")
        post = self.net.posts[res["id"]]
        self.assertEqual(post["meta"]["output_url"],
                         "https://wp/uploads/500.png")
        self.assertEqual(post["featured_media"], 500)
        self.assertEqual(post["meta"]["kind"], "image")
        self.assertEqual(post["meta"]["model"], "sdxl-lightning")
        self.assertEqual(post["status"], "private")
        self.assertTrue(post["title"]["rendered".replace("rendered", "")]
                        if isinstance(post["title"], dict)
                        else post["title"].startswith("Render — a cat"))

    def test_output_url_rejects_filesystem_path(self):
        with self.assertRaises(wpb.WpBoardsError) as cm:
            self.wp.write_render_job(
                kind="image", prompt="x",
                output_url="/local/local-gen/test-sdxl-1024.png")
        self.assertIn("must be a WP media URL", str(cm.exception))
        self.assertEqual(self.net.posts, {})

    def test_output_url_http_passthrough(self):
        res = self.wp.write_render_job(
            kind="video", prompt="clip",
            output_url="https://example.com/v.mp4")
        post = self.net.posts[res["id"]]
        self.assertEqual(post["meta"]["output_url"],
                         "https://example.com/v.mp4")
        self.assertNotIn("featured_media", post)

    def test_member_gated_output_url(self):
        res = self.wp.write_render_job(
            kind="image", prompt="x", output=self._png(),
            member_gated=True)
        post = self.net.posts[res["id"]]
        self.assertIn("/chaba/v1/media/500", post["meta"]["output_url"])

    def test_slug_upserts_existing(self):
        p = self._png()
        self.wp.write_render_job(kind="image", prompt="x", output=p,
                                 slug="render-test-1")
        self.wp.write_render_job(kind="image", prompt="x", output=p,
                                 slug="render-test-1",
                                 meta={"rating": "5"})
        self.assertEqual(len(self.net.posts), 1)
        post = next(iter(self.net.posts.values()))
        self.assertEqual(post["meta"]["rating"], "5")

    def test_unknown_meta_key_rejected(self):
        with self.assertRaises(wpb.WpBoardsError):
            self.wp.write_render_job(kind="image", prompt="x",
                                     meta={"bogus_key": "1"})

    def test_error_record_without_output(self):
        res = self.wp.write_render_job(
            kind="video", prompt="fail", status="error",
            meta={"error": "veo quota"})
        post = self.net.posts[res["id"]]
        self.assertEqual(post["meta"]["status"], "error")
        self.assertNotIn("output_url", post["meta"])

    def test_dry_run_writes_nothing(self):
        res = self.wp.write_render_job(
            kind="image", prompt="x", output=self._png(), dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertEqual(self.net.calls, [])
        self.assertEqual(self.net.posts, {})


class RenderJobRecordCliTest(unittest.TestCase):
    """scripts/ada/render-job-record.py end-to-end against the same fake."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = Path(self.tmp.name) / "wp-boards.env"
        env.write_text("WP_SITE_URL=https://fake-wp\n"
                       "WP_APP_USER=agent\nWP_APP_PASSWORD=pw\n")
        os.environ["WP_BOARDS_ENV"] = str(env)
        spec = importlib.util.spec_from_file_location(
            "render_job_record",
            REPO / "scripts" / "ada" / "render-job-record.py")
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["render_job_record"] = self.mod
        spec.loader.exec_module(self.mod)
        self.net = FakeWP()
        self._patch = mock.patch.object(
            urllib.request, "urlopen", side_effect=self.net.handle)
        self._patch.start()
        self.png = Path(self.tmp.name) / "out.png"
        self.png.write_bytes(PNG)

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()
        os.environ.pop("WP_BOARDS_ENV", None)
        sys.modules.pop("render_job_record", None)

    def test_cli_happy_path(self):
        rc = self.mod.main([
            "--kind", "image", "--prompt", "test render",
            "--output", str(self.png), "--model", "sdxl-lightning"])
        self.assertEqual(rc, 0)
        post = next(iter(self.net.posts.values()))
        self.assertEqual(post["meta"]["output_url"],
                         "https://wp/uploads/500.png")
        self.assertEqual(post["meta"]["model"], "sdxl-lightning")

    def test_cli_rejects_path_output_url(self):
        rc = self.mod.main([
            "--kind", "image", "--prompt", "x",
            "--output-url", "/local/local-gen/x.png"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.net.posts, {})


if __name__ == "__main__":
    unittest.main()
