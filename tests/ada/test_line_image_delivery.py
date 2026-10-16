"""Unit tests for the line image-delivery drop staged under
integrations/ada-voice/ (card line-delivery-send-actual-images-not-jus-652ad3,
2026-10-13).

Driver: LINE journal 2026-10-13 21:35 — Tony asked "ส่งรูปรถของผมให้หน่อย",
the persona found the car photo via drive action='search' and pasted the
webViewLink into the reply text. LINE got a text link, not an image.

The patch teaches line_relay to (a) resolve Drive share links and
/v1/drive/media/ paths into fetchable bytes via doc-archive's media-token
mint, (b) mine image-bearing URLs out of reply/send text and upgrade them
to real image messages (silent on failure — the link stays either way),
and (c) auto-attach a drive_get image via media_url when mimeType is
image/*.

Same harness as test_line_file_doc_ingest: the unified diff is applied to
a copy of the ada-voice source (ADA_PI env or ~/CascadeProjects/ada-voice),
compiled, and its helpers exercised with stubbed http. Patches already
merged upstream (ada-voice 02c5058, 2026-10-13) resolve to the live file —
tests/ada/_drops.py. Skips when no ada-voice checkout is reachable.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types as pytypes
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tests.ada._drops import apply_patch

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
PATCHES = [
    DROP / "backend" / "line_relay.image-delivery.patch",
    DROP / "backend" / "tool_guide.image-delivery.patch",
    DROP / "backend" / "realtime_provider.image-delivery.patch",
]
ADA_PI = Path(os.environ.get("ADA_PI",
                             str(Path.home() / "CascadeProjects/ada-voice")))

DRIVE_LINK = ("https://drive.google.com/file/d/"
              "1ZewCBQsfsS95C6QmytqsuZyVXtbxVJSc/view?usp=drivesdk")
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 800


@pytest.fixture()
def patched(tmp_path, monkeypatch):
    """Apply all three drop patches to a scratch ada-voice copy and import
    line_relay with httpx/websockets stubbed (not installed here)."""
    src = tmp_path / "backend"
    src.mkdir()
    for name in ("line_relay.py", "tool_guide.yml",
                 "realtime_provider.py"):
        (src / name).write_bytes((ADA_PI / "backend" / name).read_bytes())
    for p in PATCHES:
        # already-merged / post-merge-drifted patches test the live file
        apply_patch(p, tmp_path)
    for mod in ("httpx", "websockets"):
        stub = pytypes.ModuleType(mod)

        class _Any:
            def __init__(self, *a, **k):
                pass

            def __call__(self, *a, **k):
                return _Any()

        stub.AsyncClient = _Any
        stub.connect = _Any
        monkeypatch.setitem(sys.modules, mod, stub)
    monkeypatch.setenv("LINE_MEDIA_ARCHIVE_DIR", str(tmp_path / "arch"))
    monkeypatch.setenv("LINE_IMG_CACHE_DIR", str(tmp_path / "img"))
    monkeypatch.setenv("LINE_PUBLIC_IMG_BASE", "https://img.test/relay-img")
    monkeypatch.setenv("DOC_ARCHIVE_URL", "http://doc.test:11025")
    monkeypatch.setenv("DOC_ARCHIVE_API_KEY", "KEY")
    spec = importlib.util.spec_from_file_location(
        "line_relay_patched", src / "line_relay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, content=b"", mime="image/jpeg", status=200,
                 payload=None):
        self.content = content
        self.headers = {"content-type": mime}
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class _Http:
    """GET returns JPEG bytes; POST media-token mints /v1/drive/media/."""

    def __init__(self, get_resp=None):
        self.gets, self.posts = [], []
        self._get_resp = get_resp or _Resp(JPEG)

    async def get(self, url, **kw):
        self.gets.append(url)
        return self._get_resp

    async def post(self, url, json=None, headers=None, **kw):
        self.posts.append((url, json, headers or {}))
        return _Resp(payload={"url": "/v1/drive/media/FID?t=tok"})


def _relay(mod, http=None):
    relay = mod.LineRelay.__new__(mod.LineRelay)
    relay.http = http or _Http()
    relay._imgs = {}
    relay._names = {}
    return relay


# ---------------------------------------------------------------- mining

class TestMineImageUrls:
    def test_drive_share_link_in_thai_text(self, patched):
        """The exact journal line from 2026-10-13 21:35."""
        text = ("นี่คือรูปรถที่คุณโทนี่หาค่ะ: " + DRIVE_LINK)
        assert patched._mine_image_urls(text) == [DRIVE_LINK]

    def test_plain_image_ext(self, patched):
        assert patched._mine_image_urls(
            "here https://x.test/a/photo.jpeg now") == [
            "https://x.test/a/photo.jpeg"]

    def test_non_image_links_ignored(self, patched):
        assert patched._mine_image_urls(
            "page https://chaba.h3.gizmo-thailand.com/kk-ha/place-x/ "
            "map https://maps.app.goo.gl/abc123") == []

    def test_media_and_relay_img_paths(self, patched):
        out = patched._mine_image_urls(
            "http://h:11025/v1/drive/media/ABC123DEF456GHI?t=tok "
            "and /v1/drive/media/REL?t=2 and https://img/relay-img/nONCE")
        assert out == ["http://h:11025/v1/drive/media/ABC123DEF456GHI?t=tok",
                       "/v1/drive/media/REL?t=2",
                       "https://img/relay-img/nONCE"]

    def test_markdown_and_dedupe_and_cap(self, patched):
        text = ("![a](https://h/x.png) again https://h/x.png "
                "plus https://h/y.jpg and https://h/z.webp "
                "and https://h/w.gif")
        assert patched._mine_image_urls(text) == [
            "https://h/x.png", "https://h/y.jpg",
            "https://h/z.webp"]  # dedupe + limit 3


# --------------------------------------------------------------- resolve

class TestResolveDocMedia:
    def test_drive_link_mints_media_url(self, patched):
        http = _Http()
        relay = _relay(patched, http)
        url = asyncio.run(relay._resolve_doc_media(DRIVE_LINK))
        assert url == "http://doc.test:11025/v1/drive/media/FID?t=tok"
        ep, body, hdrs = http.posts[0]
        assert ep == "http://doc.test:11025/v1/drive/media-token"
        assert body["file_id"] == "1ZewCBQsfsS95C6QmytqsuZyVXtbxVJSc"
        assert hdrs["X-API-Key"] == "KEY"

    def test_open_and_uc_spellings(self, patched):
        http = _Http()
        relay = _relay(patched, http)
        for u in ("https://drive.google.com/open?id=1ZewCBQsfsS95C6Qm"
                  "ytqsuZyVXtbxVJSc",
                  "https://drive.google.com/uc?export=download&id="
                  "1ZewCBQsfsS95C6QmytqsuZyVXtbxVJSc"):
            asyncio.run(relay._resolve_doc_media(u))
        assert all(b["file_id"] == "1ZewCBQsfsS95C6QmytqsuZyVXtbxVJSc"
                   for _e, b, _h in http.posts)

    def test_relative_media_uses_doc_archive_base(self, patched):
        relay = _relay(patched)
        assert asyncio.run(relay._resolve_doc_media(
            "/v1/drive/media/X?t=1")) == \
            "http://doc.test:11025/v1/drive/media/X?t=1"

    def test_passthrough_and_no_key(self, patched, monkeypatch):
        relay = _relay(patched)
        assert asyncio.run(relay._resolve_doc_media(
            "https://x/y.jpg")) == "https://x/y.jpg"
        monkeypatch.setattr(patched, "DOC_ARCHIVE_KEY", "")
        with pytest.raises(RuntimeError, match="DOC_ARCHIVE_API_KEY"):
            asyncio.run(relay._resolve_doc_media(DRIVE_LINK))


# --------------------------------------------------------------- _image_msgs

class TestImageMsgs:
    def test_drive_link_delivers_image_message(self, patched):
        """webViewLink -> mint -> fetch -> hosted LINE image pair."""
        http = _Http()
        relay = _relay(patched, http)
        msgs = asyncio.run(relay._image_msgs(DRIVE_LINK, "car"))
        kinds = [m["type"] for m in msgs]
        assert kinds == ["image", "text"]
        assert msgs[0]["originalContentUrl"].startswith(
            "https://img.test/relay-img/")
        # the fetch hit the minted media URL, not the viewer page
        assert http.gets == ["http://doc.test:11025/v1/drive/media/FID?t=tok"]

    def test_silent_failure_returns_empty(self, patched):
        http = _Http(get_resp=_Resp(b"<html>viewer</html>",
                                    mime="text/html"))
        relay = _relay(patched, http)
        assert asyncio.run(relay._image_msgs(
            "https://x.test/page.jpg", "", silent=True)) == []
        msgs = asyncio.run(relay._image_msgs(
            "https://x.test/page.jpg", "cap", silent=False))
        assert msgs[0]["type"] == "text" and "image failed" in msgs[0]["text"]

    def test_mint_failure_inside_try_is_silent_safe(self, patched):
        """A drive link with no key must not escape _mined_msgs."""
        monkeypatched = patched
        monkeypatched.DOC_ARCHIVE_KEY = ""
        relay = _relay(monkeypatched)
        out = asyncio.run(relay._mined_msgs(
            f"photo {DRIVE_LINK}", set()))
        assert out == []


# ------------------------------------------------------------- _images_from

class TestImagesFrom:
    def test_drive_get_image_media_url(self, patched):
        # merged upstream returns (url, caption, kind) triples — the
        # video-bubble evolution added the kind element post-merge
        out = patched._images_from([{
            "mimeType": "image/jpeg",
            "media_url": "/v1/drive/media/X?t=1", "name": "car.jpg"}])
        assert out == [("/v1/drive/media/X?t=1", "", "image")]

    def test_pdf_media_url_not_an_image(self, patched):
        assert patched._images_from([{
            "mimeType": "application/pdf",
            "media_url": "/v1/drive/media/X?t=1"}]) == []

    def test_cast_url_still_wins(self, patched):
        out = patched._images_from([{
            "cast_url": "https://img.test/frame?x",
            "mimeType": "image/jpeg",
            "media_url": "/v1/drive/media/X?t=1"}])
        assert out[0][0] == "https://img.test/frame?x"


# --------------------------------------------------------------- _mined_msgs

class TestMinedMsgs:
    def test_reply_link_becomes_image(self, patched):
        relay = _relay(patched)
        msgs = asyncio.run(relay._mined_msgs(
            f"นี่รูปรถ: {DRIVE_LINK}", set()))
        assert msgs and msgs[0]["type"] == "image"

    def test_dedupes_against_tool_images(self, patched):
        relay = _relay(patched)
        seen = {DRIVE_LINK}
        assert asyncio.run(relay._mined_msgs(
            f"link {DRIVE_LINK}", seen)) == []

    def test_env_kill_switch(self, patched, monkeypatch):
        monkeypatch.setenv("LINE_TEXT_IMG_MINE", "0")
        relay = _relay(patched)
        assert asyncio.run(relay._mined_msgs(
            f"photo {DRIVE_LINK}", set())) == []
