"""Unit tests for the place_report drop staged under
integrations/ada-pi/ (card maps-url-to-cms-line-maps-link-resolved-c418f8,
2026-10-13).

The tool is already deployed on idc03 ada-kk (ada-pi 074c7a8+e24b14d) —
this suite guards the STAGED copy: pure helpers parse Google Maps URL
shapes and clean Google share strings, and run() is driven end-to-end
with a fake httpx.AsyncClient (maps expand + Nominatim) and a fake
runner.cms_publish_page that records the publish call.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-pi"
TOOL = DROP / "backend" / "tools.d" / "place_report.py"
MANIFEST = DROP / "backend" / "tools.d" / "manifest.place_report.yml"
GUIDE = DROP / "backend" / "tool_guide.place_report.yml"


def _load():
    spec = importlib.util.spec_from_file_location("place_report", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, url="", payload=None):
        self.url = url
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """httpx.AsyncClient stand-in — routes on the request URL."""

    def __init__(self, routes, calls, *a, **kw):
        self._routes = routes
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        self._calls.append(str(url))
        for pat, resp in self._routes:
            if pat in str(url):
                return resp
        raise RuntimeError(f"unstubbed GET {url}")


def _patch_httpx(monkeypatch, mod, routes):
    calls = []

    def _client(*a, **kw):
        return _FakeClient(routes, calls)

    monkeypatch.setattr(mod, "httpx",
                        SimpleNamespace(AsyncClient=_client))
    return calls


class _Runner:
    def __init__(self, fail=False):
        self.pub_calls = []
        self.fail = fail

    async def cms_publish_page(self, **kw):
        self.pub_calls.append(kw)
        if self.fail:
            raise RuntimeError("mddb down")
        return {"status": "ok",
                "public_url": "https://chaba.h3.gizmo-thailand.com/"
                              f"kk-ha/{kw['slug']}.html",
                "view_url": f"/cms/{kw['slug']}"}


# ------------------------------------------------------------- pure helpers

def test_parse_maps_url_place_and_coords():
    mod = _load()
    name, coords = mod._parse_maps_url(
        "https://www.google.com/maps/place/JJ%26J+Bistro+Cafe+and+Bar/"
        "@13.7,100.5/data=!3d13.7563!4d100.5018")
    assert name == "JJ&J Bistro Cafe and Bar"
    assert coords == "13.7563,100.5018"


def test_parse_maps_url_query_and_at():
    mod = _load()
    name, coords = mod._parse_maps_url(
        "https://www.google.com/maps?q=Waterfall+Safari+Lodge&"
        "hl=en")
    assert name == "Waterfall Safari Lodge"
    name2, coords2 = mod._parse_maps_url(
        "https://maps.google.com/@17.9,102.7,15z")
    assert coords2 == "17.9,102.7"


def test_strip_code_tokens_keeps_business_name():
    mod = _load()
    out = mod._strip_code_tokens("3302 PQRJ 452 JJ&J Bistro Cafe and Bar")
    assert out == "JJ&J Bistro Cafe and Bar"
    # a real leading token that isn't a code survives
    assert mod._strip_code_tokens("JJ&J Bistro") == "JJ&J Bistro"


def test_short_name_drops_address_tail():
    mod = _load()
    assert mod._short_name(
        "JJ&J Bistro Cafe and Bar, 3302 Bangkok") == \
        "JJ&J Bistro Cafe and Bar"
    assert mod._short_name("Cafe 12/3 Soi 5").startswith("Cafe")


def test_slug_stable_ascii_prefixed():
    mod = _load()
    s1 = mod._slug_for(None, "JJ&J Bistro Café", "13.7,100.5")
    s2 = mod._slug_for(None, "JJ&J Bistro Café", "13.7,100.5")
    assert s1 == s2 and s1.startswith("place-")
    assert all(c.isascii() and (c.isalnum() or c == "-") for c in s1)


def test_page_th_includes_map_links_and_question():
    mod = _load()
    title, body = mod._page(
        {"name": "Waterfall Safari Lodge",
         "address": "Kanchanaburi",
         "coords": "14.0,99.5",
         "display_name": "",
         "resolved_url": "https://maps.google.com/?q=x"},
        "ร้านนี้ยังอยู่มั้ย", "th")
    assert "รายงานสถานที่" in title
    assert "staticmap.openstreetmap.de" in body
    assert "Google Maps" in body and "OpenStreetMap" in body
    assert "## คำถาม" in body and "ร้านนี้ยังอยู่มั้ย" in body


# ----------------------------------------------------------------- run()

def test_run_maps_url_full_flow(monkeypatch):
    mod = _load()
    calls = _patch_httpx(monkeypatch, mod, [
        ("maps.app.goo.gl", _Resp(
            url="https://www.google.com/maps/place/JJ%26J+Bistro/"
                "@13.7,100.5/data=!3d13.7563!4d100.5018")),
        ("nominatim", _Resp(payload={
            "display_name": "JJ&J Bistro, Bangkok",
            "address": {"amenity": "JJ&J Bistro"}})),
    ])
    runner = _Runner()
    out = asyncio.run(mod.run(
        runner, url="https://maps.app.goo.gl/abc123",
        ask="is this shop still open?", lang="en"))
    assert out["ok"] and out["name"] == "JJ&J Bistro"
    assert out["coords"] == "13.7563,100.5018"
    assert out["publish"]["public_url"].endswith(".html")
    pub = runner.pub_calls[0]
    assert pub["public"] == "true" and pub["domain"] == "places"
    assert pub["slug"].startswith("place-")
    # expanded once, then reverse-geocoded
    assert any("maps.app.goo.gl" in c for c in calls)
    assert any("/reverse" in c for c in calls)


def test_run_extracts_url_from_ask(monkeypatch):
    mod = _load()
    _patch_httpx(monkeypatch, mod, [
        ("maps.app.goo.gl", _Resp(
            url="https://www.google.com/maps/place/X/@0,0/data=!3d1.0!4d2.0")),
        ("nominatim", _Resp(payload={"display_name": "X"})),
    ])
    out = asyncio.run(mod.run(
        _Runner(), ask="ที่นี่ยังเปิดมั้ย https://maps.app.goo.gl/zz9"))
    assert out["ok"] and out["coords"] == "1.0,2.0"


def test_run_place_name_search_path(monkeypatch):
    mod = _load()
    _patch_httpx(monkeypatch, mod, [
        ("nominatim", _Resp(payload=[{
            "lat": "13.7", "lon": "100.5",
            "display_name": "Some Cafe, Bangkok",
            "name": "Some Cafe"}])),
    ])
    runner = _Runner()
    out = asyncio.run(mod.run(runner, place="Some Cafe Bangkok"))
    assert out["ok"] and out["coords"] == "13.7,100.5"
    assert runner.pub_calls[0]["slug"].startswith("place-")


def test_run_no_input_errors():
    mod = _load()
    out = asyncio.run(mod.run(_Runner()))
    assert not out["ok"] and "maps url or a place name" in out["error"]


def test_run_publish_failure_is_honest(monkeypatch):
    mod = _load()
    _patch_httpx(monkeypatch, mod, [
        ("maps.app.goo.gl", _Resp(
            url="https://www.google.com/maps/place/Y/@0,0/data=!3d1.0!4d2.0")),
        ("nominatim", _Resp(payload={"display_name": "Y"})),
    ])
    out = asyncio.run(mod.run(
        _Runner(fail=True), url="https://maps.app.goo.gl/zz9"))
    assert not out["ok"] and "don't claim it was sent" in out["error"]


def test_run_no_name_no_coords_errors(monkeypatch):
    mod = _load()
    _patch_httpx(monkeypatch, mod, [
        ("maps.app.goo.gl", _Resp(
            url="https://www.google.com/maps/@13.0,100.0,15z")),
        ("nominatim", _Resp(payload={"display_name": "",
                                     "address": {}})),
    ])
    # @lat,lng gives coords so this actually succeeds — the error path
    # needs a resolved URL with neither name nor coords
    _patch_httpx(monkeypatch, mod, [
        ("maps.app.goo.gl", _Resp(url="https://www.google.com/maps")),
        ("nominatim", _Resp(payload=[])),
    ])
    out = asyncio.run(mod.run(_Runner(), url="https://maps.app.goo.gl/z"))
    assert not out["ok"] and "no place name" in out["error"]


def test_run_unresolved_place_refuses_publish(monkeypatch):
    """Bare place= ask + Nominatim miss (the Cape Sports Center
    Langebaan page): nothing mappable -> no page, unresolved +
    maps/search fallback link."""
    mod = _load()
    _patch_httpx(monkeypatch, mod, [
        ("nominatim", _Resp(payload=[])),
    ])
    runner = _Runner()
    out = asyncio.run(mod.run(
        runner, place="Cape Sports Center Langebaan",
        ask="ขอแผนที่", lang="th"))
    assert not out["ok"] and out["unresolved"]
    assert runner.pub_calls == []  # the bug was a title-only publish
    assert out["maps_url"].startswith(
        "https://www.google.com/maps/search/?api=1&query=")
    assert "Cape+Sports+Center+Langebaan" in out["maps_url"]
    assert "NO page was published" in out["error"]


def test_run_unresolved_place_nominatim_down_still_honest(monkeypatch):
    """Nominatim throwing on the name search lands on the same
    unresolved path — no publish, fallback link."""
    mod = _load()
    _patch_httpx(monkeypatch, mod, [])  # every GET raises
    runner = _Runner()
    out = asyncio.run(mod.run(runner, place="Some Unfindable Cafe"))
    assert not out["ok"] and out["unresolved"]
    assert runner.pub_calls == []
    assert "maps/search" in out["maps_url"]


def test_run_expand_failure_reports(monkeypatch):
    mod = _load()
    _patch_httpx(monkeypatch, mod, [])  # every GET raises
    out = asyncio.run(mod.run(_Runner(), url="https://maps.app.goo.gl/x"))
    assert not out["ok"] and "did not resolve" in out["error"]


# ----------------------------------------------------------- drop registry

def test_manifest_fragment_matches_declaration():
    mod = _load()
    frag = yaml.safe_load(MANIFEST.read_text())
    entry = frag["place_report"]
    assert entry["module"] == "place_report"
    assert entry["policy"] == "read"
    assert mod.DECLARATION["name"] == "place_report"
    props = mod.DECLARATION["parameters"]["properties"]
    assert {"url", "place", "ask", "lang"} <= set(props)


def test_tool_guide_fragment_has_key():
    frag = yaml.safe_load(GUIDE.read_text())
    assert "place_report" in frag
    assert "public_url" in frag["place_report"]
