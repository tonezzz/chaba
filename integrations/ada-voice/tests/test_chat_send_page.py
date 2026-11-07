"""chat_send page=<slug> (card chat-send-page-images, ADA-0511).

Kaewta's photo-ask path was nondeterministic: cms_read + image_url +
deliver sometimes invented URLs (surf-thailand.com/kk/…, unsplash →
404s) or sent text-only phantoms naming the page. page= reads the CMS
doc inside the background job, extracts every embedded image, and
pushes the batch through the relay /send image_urls contract — one
call, no URLs for the model to fabricate, and the note reports
sent/failed per asset.

Covered:

- _page_image_urls: markdown ![..](..) + <img src> extraction in
  document order, dedupe, data: skip, site-relative resolution against
  LINE_URL_BASE, the ADA cap.
- _chat_send_page_run: page read -> image_urls payload to the lane
  relay; the relay's 'images' report -> an honest sent/failed note;
  missing/empty page -> FAILED, nothing POSTed to a relay.
- relay /send image_urls: each asset becomes an image bubble, a >5
  batch rides consecutive pushes (the msgs[:5] truncate is gone), and
  the response 'images' list reports per-URL delivered/fetch-failed.
- tg /send image_urls: one send_photo per asset, per-URL status back.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend import line_relay, tg_relay
from backend.tool_runner import ToolRunner
from backend.tool_runner.chat import (
    _chat_page_img_max, _page_image_urls)


class PageImageUrlTests(unittest.TestCase):

    def test_markdown_absolute_and_relative(self):
        content = (
            "# page\n"
            "![beach](https://cdn.example.com/a.jpg)\n"
            "text ![two](/api/documents/b.png) more\n")
        urls, skipped = _page_image_urls(content, 10)
        self.assertEqual(urls, [
            "https://cdn.example.com/a.jpg",
            "http://100.102.134.91:11023/api/documents/b.png"])
        self.assertEqual(skipped, 0)

    def test_img_tags_and_doc_order(self):
        content = ('<img src="/media/1.jpg"> then ![b](/media/2.jpg) '
                   'then <img src="https://x.test/c.jpg">')
        urls, _ = _page_image_urls(content, 10)
        self.assertEqual(urls, [
            "http://100.102.134.91:11023/media/1.jpg",
            "http://100.102.134.91:11023/media/2.jpg",
            "https://x.test/c.jpg"])

    def test_dedupe_and_non_images_ignored(self):
        content = ("![a](/a.jpg) [link](/a.jpg) ![a2](/a.jpg) "
                   "![b](data:image/png;base64,AAAA) ![c](//cdn.x/c.jpg)")
        urls, _ = _page_image_urls(content, 10)
        self.assertEqual(urls, [
            "http://100.102.134.91:11023/a.jpg",
            "https://cdn.x/c.jpg"])

    def test_line_url_base_env_wins(self):
        with patch.dict(os.environ,
                        {"LINE_URL_BASE": "https://site.test/base"}):
            urls, _ = _page_image_urls("![x](/p.jpg)", 10)
        self.assertEqual(urls, ["https://site.test/base/p.jpg"])

    def test_cap_reports_skipped(self):
        content = "".join(f"![{i}](/i{i}.jpg)" for i in range(7))
        urls, skipped = _page_image_urls(content, 5)
        self.assertEqual(len(urls), 5)
        self.assertEqual(skipped, 2)

    def test_img_max_env(self):
        with patch.dict(os.environ, {"ADA_CHAT_PAGE_IMG_MAX": "3"}):
            self.assertEqual(_chat_page_img_max(), 3)


def _runner() -> ToolRunner:
    ha = AsyncMock()
    ha.base_url = "http://test:8123"
    r = ToolRunner(ha, habit_state_getter=lambda: {"habits": []},
                   instance_id="test")
    r.mddb = AsyncMock()
    return r


class _FakeResp:
    """urlopen context-manager returning a fixed JSON body."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ChatSendPageRunTests(unittest.IsolatedAsyncioTestCase):
    """The background job: mddb read -> batch POST -> notify note."""

    async def asyncSetUp(self):
        self.runner = _runner()
        self.posts: list[tuple[str, dict]] = []

        def fake_urlopen(req, timeout=0, **kw):
            body = json.loads(req.data.decode())
            self.posts.append((req.full_url, body))
            if req.full_url.endswith("/send"):
                imgs = [{"url": u, "ok": True, "status": "delivered"}
                        for u in body.get("image_urls") or []]
                if body.get("image_url"):
                    imgs.append({"url": body["image_url"], "ok": True,
                                 "status": "delivered"})
                return _FakeResp({"ok": True, "to": body.get("to"),
                                  "images": imgs})
            return _FakeResp({"ok": True})

        self._up = patch("urllib.request.urlopen", fake_urlopen)
        self._up.start()
        self.addCleanup(self._up.stop)
        self.runner.cms_get_page = AsyncMock(return_value={
            "slug": "sa-beach-photos", "title": "SA Beach Photos",
            "content": ("![a](/api/documents/a.jpg)\n"
                        "![b](https://cdn.test/b.png)\n")})

    def _sends(self):
        return [b for url, b in self.posts if url.endswith("/send")]

    def _notify(self):
        notes = [b for url, b in self.posts if url.endswith("/notify")]
        return notes[-1]["text"] if notes else ""

    async def test_queued_contract(self):
        # the create_task job fires on the loop — stub it so this test
        # stays on the queued-return contract only.
        self.runner._chat_send_page_run = AsyncMock()
        out = await self.runner.chat_send(channel="line",
                                          page="sa-beach-photos")
        self.assertEqual(out["status"], "queued")
        self.assertEqual(out["page"], "sa-beach-photos")

    async def test_page_batch_posts_image_urls(self):
        await self.runner._chat_send_page_run(
            "job-x", "sa-beach-photos", channel="line",
            text="photos!", to="U1")
        sends = self._sends()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["image_urls"], [
            "http://100.102.134.91:11023/api/documents/a.jpg",
            "https://cdn.test/b.png"])
        self.assertEqual(sends[0]["to"], "U1")
        self.assertIn("line: 2/2 images delivered", self._notify())
        self.assertIn("DONE", self._notify())

    async def test_per_asset_failures_named_in_note(self):
        def flaky(req, timeout=0, **kw):
            body = json.loads(req.data.decode())
            self.posts.append((req.full_url, body))
            if req.full_url.endswith("/send"):
                imgs = []
                for i, u in enumerate(body.get("image_urls") or []):
                    imgs.append({"url": u, "ok": i == 0,
                                 "status": "delivered" if i == 0
                                 else "fetch-failed"})
                return _FakeResp({"ok": True, "images": imgs})
            return _FakeResp({"ok": True})
        with patch("urllib.request.urlopen", flaky):
            await self.runner._chat_send_page_run(
                "job-y", "sa-beach-photos", channel="line", text="",
                to="U1")
        note = self._notify()
        self.assertIn("line: 1/2 images delivered", note)
        self.assertIn("failed https://cdn.test/b.png (fetch-failed)",
                      note)
        self.assertIn("DONE", note)

    async def test_missing_page_fails_without_relay_post(self):
        self.runner.cms_get_page = AsyncMock(return_value={
            "ok": False, "error": "no page 'nope' in ada-cms-pages"})
        await self.runner._chat_send_page_run(
            "job-z", "nope", channel="line", text="", to="U1")
        self.assertEqual(self._sends(), [])
        self.assertIn("FAILED", self._notify())
        self.assertIn("nothing sent", self._notify())

    async def test_imageless_page_with_text_still_sends_text(self):
        self.runner.cms_get_page = AsyncMock(return_value={
            "slug": "p", "content": "no pictures here"})
        await self.runner._chat_send_page_run(
            "job-t", "p", channel="line", text="read this", to="U1")
        sends = self._sends()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["text"], "read this")
        self.assertEqual(sends[0]["image_urls"], [])
        self.assertIn("embeds no images", self._notify())

    async def test_imageless_page_no_text_is_honest_fail(self):
        self.runner.cms_get_page = AsyncMock(return_value={
            "slug": "p", "content": "no pictures here"})
        await self.runner._chat_send_page_run(
            "job-n", "p", channel="line", text="", to="U1")
        self.assertEqual(self._sends(), [])
        self.assertIn("FAILED", self._notify())

    async def test_old_relay_without_images_report_still_done(self):
        def legacy(req, timeout=0, **kw):
            body = json.loads(req.data.decode())
            self.posts.append((req.full_url, body))
            return _FakeResp({"ok": True, "to": "U1"})
        with patch("urllib.request.urlopen", legacy):
            await self.runner._chat_send_page_run(
                "job-o", "sa-beach-photos", channel="line", text="",
                to="U1")
        self.assertIn("no per-asset report", self._notify())
        self.assertIn("DONE", self._notify())


class RelayImageBatchTests(unittest.TestCase):
    """line_relay /send image_urls — bubbles, chunking, per-URL report."""

    def _app(self):
        import uvicorn
        captured = {}

        class _Srv:
            def __init__(self, config):
                captured["app"] = config.app

            async def serve(self):
                return None

        relay = line_relay.LineRelay()
        relay._deliver = AsyncMock(return_value="delivered")
        relay.http = MagicMock()

        async def fake_image(url, caption, silent=False):
            if "bad" in url:
                return [{"type": "text",
                         "text": f"(image failed: {url})"}]
            return [{"type": "image", "originalContentUrl": url,
                     "previewImageUrl": url}]
        relay._image_msgs = fake_image
        with patch.object(line_relay, "CHANNEL_SECRET", "x"), \
                patch.object(uvicorn, "Server", _Srv):
            asyncio.run(relay._webhook_server())
        return captured["app"], relay

    def test_batch_reports_per_url_and_chunks(self):
        from starlette.testclient import TestClient
        with tempfile.TemporaryDirectory() as tmp:
            line_relay.PARKED_DIR = Path(tmp)
            line_relay.SEND_LEDGER_FILE = Path(tmp) / "send-ledger.json"
            app, relay = self._app()
            client = TestClient(app)
            urls = [f"https://img.test/{i}.jpg" for i in range(7)]
            r = client.post("/send", json={
                "to": "U1", "text": "photos", "image_urls": urls})
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertTrue(body["ok"])
            # 1 text + 7 images = 8 bubbles -> two pushes (5 + 3).
            self.assertEqual(relay._deliver.await_count, 2)
            first = relay._deliver.await_args_list[0].args[1]
            second = relay._deliver.await_args_list[1].args[1]
            self.assertEqual(len(first), 5)
            self.assertEqual(len(second), 3)
            imgs = body["images"]
            self.assertEqual(len(imgs), 7)
            self.assertTrue(all(i["ok"] for i in imgs))
            self.assertTrue(all(i["status"] == "delivered"
                                for i in imgs))
            self.assertEqual([i["url"] for i in imgs], urls)

    def test_fetch_failed_asset_reported_not_sent(self):
        from starlette.testclient import TestClient
        with tempfile.TemporaryDirectory() as tmp:
            line_relay.PARKED_DIR = Path(tmp)
            line_relay.SEND_LEDGER_FILE = Path(tmp) / "send-ledger.json"
            app, relay = self._app()
            client = TestClient(app)
            r = client.post("/send", json={
                "to": "U1",
                "image_urls": ["https://img.test/ok.jpg",
                               "https://img.test/bad.jpg"]})
            imgs = r.json()["images"]
            self.assertEqual(imgs[0]["status"], "delivered")
            self.assertEqual(imgs[1]["status"], "fetch-failed")
            self.assertFalse(imgs[1]["ok"])
            # the failure stays honest in-chat: its "(image failed)"
            # text bubble rides the same push.
            msgs = relay._deliver.await_args.args[1]
            self.assertTrue(any(m.get("type") == "text" and
                                "image failed" in m.get("text", "")
                                for m in msgs))

    def test_singular_image_url_also_reports(self):
        from starlette.testclient import TestClient
        with tempfile.TemporaryDirectory() as tmp:
            line_relay.PARKED_DIR = Path(tmp)
            line_relay.SEND_LEDGER_FILE = Path(tmp) / "send-ledger.json"
            app, relay = self._app()
            client = TestClient(app)
            r = client.post("/send", json={
                "to": "U1", "image_url": "https://img.test/s.jpg"})
            self.assertEqual(r.json()["images"],
                             [{"url": "https://img.test/s.jpg",
                               "ok": True, "status": "delivered"}])


class TgImageBatchTests(unittest.TestCase):
    """tg_relay /send image_urls — per-asset send_photo + report."""

    def _endpoint(self, relay):
        from starlette.applications import Starlette
        from starlette.routing import Route
        return Starlette(routes=[Route(
            "/send", relay._send_endpoint(), methods=["POST"])])

    def test_batch_sends_each_photo_and_reports(self):
        from starlette.testclient import TestClient
        relay = tg_relay.TgRelay()
        relay.send_text = AsyncMock()
        sent: list[str] = []

        async def fake_photo(cid, url, caption):
            sent.append(url)
            return "bad" not in url
        relay.send_photo = fake_photo
        app = self._endpoint(relay)
        with patch.dict(os.environ, {"TG_ALLOWED_CHATS": "5"}):
            client = TestClient(app)
            r = client.post("/send", json={
                "chat_id": 5, "text": "t",
                "image_urls": ["https://i.test/a.jpg",
                               "https://i.test/bad.jpg"]})
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(sent, ["https://i.test/a.jpg",
                                "https://i.test/bad.jpg"])
        self.assertEqual(body["images"], [
            {"url": "https://i.test/a.jpg", "ok": True,
             "status": "delivered"},
            {"url": "https://i.test/bad.jpg", "ok": False,
             "status": "failed"}])


if __name__ == "__main__":
    unittest.main()
