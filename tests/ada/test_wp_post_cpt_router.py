"""Unit tests for the wp_post CPT-router drop staged under
integrations/ada-voice/ (card line-cpt-writer-router, 2026-10-15).

boards.surf-thailand.com has chaba-boards CPTs (asset, expense, contact,
reminder, ...). Until now every LINE "post this" ask landed as a
free-form post. The patch adds kind= to wp_post so save-asks route to
the right CPT with whitelisted meta: receipts -> expense (missing
fields OCR'd off the attached photo via the lane's Gemini pool),
contacts -> contact, "remind us" -> reminder, assets -> asset. CPT
records publish as private (member-only, the /chat/line/* model) and
get the "<Kind> — <title>" title standard automatically.

Harness like test_line_image_delivery: the unified diff is applied to a
scratch copy of the ada-voice sources (ADA_PI env or
~/CascadeProjects/ada-voice), then the patched module is exercised with
a fake httpx.AsyncClient and a stub backend.gemini_pool. Skips when no
ada-voice checkout is reachable (the patch is what ships, not the file).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import types as pytypes
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
PATCH = REPO / "integrations" / "ada-voice" / "backend" / "tools.d" / \
    "wp_post.cpt-router.patch"
ADA_PI = Path(os.environ.get(
    "ADA_PI", str(Path.home() / "CascadeProjects/ada-voice")))

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 400
PDF = b"%PDF-1.4 fake manual bytes"

OCR_JSON = json.dumps({
    "amount": "129.00", "currency": "THB", "vendor": "Tops Market",
    "receipt_date": "2026-10-14", "paid_by": None})


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class _HTTP:
    """Fake httpx.AsyncClient — records (method, route, kwargs) and
    answers the wp_client calls: GET tags, POST media, POST <route>."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, **kw):
        route = urllib.parse.unquote(
            url.split("rest_route=", 1)[1].split("&", 1)[0])
        self.calls.append((method, route, kw))
        if route == "/wp/v2/tags":
            return _Resp(200 if method == "GET" else 201, [{"id": 7}])
        if route == "/wp/v2/media":
            return _Resp(201, {
                "id": 55,
                "source_url": "https://boards.h3.gizmo-thailand.com/wp/"
                              "wp-content/uploads/2026/10/f.jpg"})
        return _Resp(201, {
            "id": 900,
            "link": "https://boards.h3.gizmo-thailand.com/wp/"
                    "index.php/rec-1/"})

    def posts(self, route):
        return [kw["json"] for m, r, kw in self.calls
                if m == "POST" and r == route]


@pytest.fixture()
def wp_post_mod(tmp_path, monkeypatch):
    """Apply the drop patch to a scratch ada-voice tree and import the
    patched wp_post with a stub backend.gemini_pool."""
    if not (ADA_PI / "backend" / "tools.d" / "wp_post.py").is_file():
        pytest.skip("no ada-voice checkout at ADA_PI")
    src = tmp_path / "src"
    (src / "backend" / "tools.d").mkdir(parents=True)
    (src / "backend" / "__init__.py").write_text("")
    (src / "backend" / "tools.d" / "__init__.py").write_text("")
    (src / "backend" / "tools.d" / "wp_post.py").write_bytes(
        (ADA_PI / "backend" / "tools.d" / "wp_post.py").read_bytes())
    (src / "backend" / "wp_client.py").write_bytes(
        (ADA_PI / "backend" / "wp_client.py").read_bytes())
    # gemini_pool stub — records calls, returns OCR_JSON by default.
    (src / "backend" / "gemini_pool.py").write_text(
        "from types import SimpleNamespace\n"
        "class QuotaExhaustedError(RuntimeError):\n"
        "    pass\n"
        "RESP = ''\n"
        "RAISE = None\n"
        "CALLS = []\n"
        "async def generate(model=None, contents=None, config=None,\n"
        "                   client=None, timeout=None, tool='',\n"
        "                   mddb=None, session_id=''):\n"
        "    CALLS.append({'model': model, 'tool': tool})\n"
        "    if RAISE:\n"
        "        raise RAISE\n"
        "    return SimpleNamespace(text=RESP)\n")
    r = subprocess.run(["git", "apply", "--check", str(PATCH)],
                       cwd=src, capture_output=True, text=True)
    assert r.returncode == 0, f"patch no longer applies: {r.stderr}"
    subprocess.run(["git", "apply", str(PATCH)], cwd=src, check=True)

    # google.genai.types stub for Part.from_bytes (the lazy OCR import).
    gtypes = pytypes.ModuleType("google.genai.types")

    class _Part:
        @staticmethod
        def from_bytes(data=None, mime_type=None):
            return {"data_len": len(data or b""), "mime": mime_type}

    gtypes.Part = _Part
    ggenai = pytypes.ModuleType("google.genai")
    ggenai.types = gtypes
    monkeypatch.setitem(sys.modules, "google", pytypes.ModuleType("google"))
    sys.modules["google"].genai = ggenai
    monkeypatch.setitem(sys.modules, "google.genai", ggenai)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)

    monkeypatch.syspath_prepend(str(src))
    import importlib.util
    # Force OUR scratch backend package — a previous suite may leave a
    # 'backend' stub in sys.modules pointing at its own tree.
    backend_pkg = pytypes.ModuleType("backend")
    backend_pkg.__path__ = [str(src / "backend")]
    monkeypatch.setitem(sys.modules, "backend", backend_pkg)
    for name in ("backend.wp_client", "backend.gemini_pool"):
        sys.modules.pop(name, None)
    import backend.wp_client  # noqa: F401
    import backend.gemini_pool  # noqa: F401
    spec = importlib.util.spec_from_file_location(
        "wp_post_patched", src / "backend" / "tools.d" / "wp_post.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    http = _HTTP()
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: http)

    env_file = tmp_path / "wp-boards.env"
    env_file.write_text(
        "WP_SITE_URL=https://boards.test/wp\n"
        "WP_APP_USER=ada\n"
        "WP_APP_PASSWORD=xxxx xxxx xxxx xxxx\n")
    monkeypatch.setattr(mod.wp, "ENV_FILE", str(env_file))
    arch = tmp_path / "arch"
    arch.mkdir()
    monkeypatch.setattr(mod.wp, "MEDIA_ROOT", str(arch))
    import backend.gemini_pool as gp
    gp.RESP = "```json\n" + OCR_JSON + "\n```"
    gp.RAISE = None
    gp.CALLS.clear()
    return SimpleNamespace(mod=mod, http=http, arch=arch, gp=gp)


def _run(env, **args):
    return asyncio.run(env.mod.run(SimpleNamespace(context=None), **args))


def _add_media(env, rel="chat1/receipt.bin", data=JPEG):
    p = env.arch / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return f"https://relay.test/relay-img/arch/{rel}"


class TestPostKindUnchanged:
    def test_default_kind_is_public_post_with_tag(self, wp_post_mod):
        env = wp_post_mod
        out = _run(env, person="kk", title="Hi", content="hello there")
        assert out["ok"] and out["kind"] == "post"
        assert out["status"] == "publish"
        assert out["tag_archive"].endswith("/tag/kk/")
        posts = env.http.posts("/wp/v2/posts")
        assert len(posts) == 1
        assert posts[0]["tags"] == [7]
        assert posts[0]["status"] == "publish"
        assert "meta" not in posts[0]


class TestExpenseOcr:
    def test_receipt_photo_ocr_fills_meta(self, wp_post_mod):
        env = wp_post_mod
        media = _add_media(env)
        out = _run(env, person="kk", kind="expense",
                   title="lunch receipt", content="receipt",
                   media_url=media)
        assert out["ok"], out
        posts = env.http.posts("/wp/v2/expense")
        assert len(posts) == 1
        p = posts[0]
        assert p["status"] == "private"           # member-only, not public
        assert p["title"] == "Expense — lunch receipt"
        assert p["meta"]["amount"] == "129.00"
        assert p["meta"]["vendor"] == "Tops Market"
        assert p["meta"]["receipt_date"] == "2026-10-14"
        assert p["featured_media"] == 55
        assert "<img" in p["content"]
        assert env.gp.CALLS and env.gp.CALLS[0]["tool"] == "wp_post"
        assert out["ocr"]["vendor"] == "Tops Market"

    def test_caller_meta_wins_over_ocr(self, wp_post_mod):
        env = wp_post_mod
        media = _add_media(env)
        out = _run(env, person="kk", kind="expense", title="r",
                   content="x", media_url=media,
                   meta={"amount": "50", "paid_by": "kk"})
        p = env.http.posts("/wp/v2/expense")[0]
        assert p["meta"]["amount"] == "50"        # caller wins
        assert p["meta"]["paid_by"] == "kk"
        assert p["meta"]["vendor"] == "Tops Market"  # OCR fills the rest
        assert "amount" not in (out["ocr"] or {})

    def test_ocr_failure_still_posts(self, wp_post_mod):
        env = wp_post_mod
        env.gp.RAISE = RuntimeError("quota")
        media = _add_media(env)
        out = _run(env, person="kk", kind="expense", title="r",
                   content="x", media_url=media, meta={"vendor": "7-11"})
        assert out["ok"]
        p = env.http.posts("/wp/v2/expense")[0]
        assert p["meta"] == {"vendor": "7-11"}
        assert out["ocr"] is None


class TestContactReminderAsset:
    def test_contact_meta_whitelisted(self, wp_post_mod):
        env = wp_post_mod
        out = _run(env, person="kk", kind="contact", title="Somchai",
                   content="plumber",
                   meta={"phone": "081-234-5678", "role": "plumber",
                         "line_id": "somchai1", "bogus": "drop me"})
        assert out["ok"], out
        p = env.http.posts("/wp/v2/contact")[0]
        assert p["status"] == "private"
        assert p["title"] == "Contact — Somchai"
        assert p["meta"] == {"phone": "081-234-5678", "role": "plumber",
                             "line_id": "somchai1"}
        assert out["dropped_meta"] == ["bogus"]
        assert not env.gp.CALLS     # no OCR off the expense path

    def test_reminder(self, wp_post_mod):
        env = wp_post_mod
        out = _run(env, person="kk", kind="reminder",
                   title="water the plants", content="daily",
                   meta={"due_date": "2026-10-30", "assignee": "kk"})
        assert out["ok"]
        p = env.http.posts("/wp/v2/reminder")[0]
        assert p["title"] == "Reminder — water the plants"
        assert p["meta"]["due_date"] == "2026-10-30"
        assert p["status"] == "private"

    def test_asset_pdf_manual_attaches_as_link(self, wp_post_mod):
        env = wp_post_mod
        media = _add_media(env, "chat1/crv-manual.bin", PDF)
        out = _run(env, person="kk", kind="asset", title="CR-V",
                   content="car manual", media_url=media,
                   meta={"model": "CR-V", "vendor": "Honda"})
        assert out["ok"], out
        p = env.http.posts("/wp/v2/asset")[0]
        assert p["title"] == "Asset — CR-V"
        assert p["meta"]["model"] == "CR-V"
        assert "featured_media" not in p          # pdf is no thumbnail
        assert '<a href="https://boards.surf-thailand.com/' in p["content"]

    def test_existing_prefix_not_doubled(self, wp_post_mod):
        env = wp_post_mod
        _run(env, person="kk", kind="asset",
             title="Asset — Washer", content="x")
        p = env.http.posts("/wp/v2/asset")[0]
        assert p["title"] == "Asset — Washer"


class TestGuards:
    def test_invalid_kind(self, wp_post_mod):
        out = _run(wp_post_mod, person="kk", kind="banana",
                   title="t", content="c")
        assert not out["ok"] and "kind" in out["error"]

    def test_draft_preview_keeps_cpt(self, wp_post_mod):
        env = wp_post_mod
        out = _run(env, person="kk", kind="reminder", title="t",
                   content="c", publish=False)
        assert out["ok"]
        p = env.http.posts("/wp/v2/reminder")[0]
        assert p["status"] == "draft"
        assert out["status"] == "draft"

    def test_media_not_in_archive_still_posts(self, wp_post_mod):
        env = wp_post_mod
        out = _run(env, person="kk", kind="expense", title="t",
                   content="c",
                   media_url="https://relay.test/relay-img/arch/x/no.bin")
        assert out["ok"] and "skipped" in (out["note"] or "")
