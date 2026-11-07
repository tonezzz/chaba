"""Unit tests for the map_embed drop staged under
integrations/ada-voice/ (card map-embed-tool, 2026-10-27).

The tool is a pure builder — the suite drives the URL composers
directly and run() end-to-end with a fake httpx.AsyncClient (Routes
API POST + Nominatim GET) and monkeypatched GOOGLE_MAPS_API_KEY for
the key/no-key forks. No CMS writes happen anywhere in this tool —
the contract is honest snippet output (needs_key / unresolved
coordinates degrade to ok:false plus the keyless open_url).
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
TOOL = DROP / "backend" / "tools.d" / "map_embed.py"
MANIFEST = DROP / "backend" / "tools.d" / "manifest.map_embed.yml"
GUIDE = DROP / "backend" / "tool_guide.map_embed.yml"
SCENARIO = DROP / "tests" / "scenarios-live" / "map_embed.yaml"


def _load():
    spec = importlib.util.spec_from_file_location("map_embed", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, payload=None):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """httpx.AsyncClient stand-in — routes GETs and POSTs on the
    request URL; records (method, url, json) for assertions."""

    def __init__(self, routes, calls, *a, **kw):
        self._routes = routes
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        self._calls.append(("get", str(url), params))
        for pat, resp in self._routes:
            if pat in str(url):
                return resp
        raise RuntimeError(f"unstubbed GET {url}")

    async def post(self, url, json=None, headers=None):
        self._calls.append(("post", str(url), json))
        for pat, resp in self._routes:
            if pat in str(url):
                return resp
        raise RuntimeError(f"unstubbed POST {url}")


def _patch_httpx(monkeypatch, mod, routes):
    calls = []

    def _client(*a, **kw):
        return _FakeClient(routes, calls)

    monkeypatch.setattr(mod, "httpx",
                        SimpleNamespace(AsyncClient=_client))
    return calls


def _qs(url):
    return parse_qs(urlparse(url).query)


# ------------------------------------------------------------- inputs

def test_place_normalization():
    mod = _load()
    assert _load()._place("Cape Town") == {
        "name": "Cape Town", "coords": "", "query": "Cape Town"}
    p = mod._place({"name": "CPT", "lat": -33.92, "lon": 18.42})
    assert p["coords"] == "-33.920000,18.420000"
    assert p["query"] == "-33.920000,18.420000"  # coords win
    bad = mod._place({"name": "X", "lat": "oops", "lon": 1})
    assert bad["coords"] == "" and bad["query"] == "X"


def test_route_arg_parse():
    mod = _load()
    r = mod._route_arg({"origin": "Bangkok",
                        "destination": {"name": "Hua Hin"},
                        "waypoints": ["Cha-am", {"name": ""}],
                        "mode": "WALKING"})
    assert r["mode"] == "walking"
    assert [w["query"] for w in r["waypoints"]] == ["Cha-am"]
    assert mod._route_arg({"origin": "A"}) is None  # no destination
    assert mod._route_arg("Bangkok") is None


def test_places_arg_accepts_strings_and_single():
    mod = _load()
    out = mod._places_arg(["A", {"name": "B", "lat": 1, "lon": 2}])
    assert [p["query"] for p in out] == ["A", "1.000000,2.000000"]
    assert len(mod._places_arg({"name": "solo"})) == 1
    assert mod._places_arg(None) == []


# ------------------------------------------------------------- URL builders

def test_open_url_single_place_and_route():
    mod = _load()
    p = [{"name": "Cape Town", "coords": "", "query": "Cape Town"}]
    assert mod._open_url(p, None).startswith(
        "https://www.google.com/maps/search/?api=1&query=")
    r = {"origin": p[0], "destination": {"name": "Stellenbosch",
                                         "coords": "", "query": "Stellenbosch"},
         "waypoints": [{"name": "Paarl", "coords": "", "query": "Paarl"}],
         "mode": "driving"}
    q = _qs(mod._open_url([], r))
    assert q["origin"] == ["Cape Town"]
    assert q["waypoints"] == ["Paarl"]
    assert q["destination"] == ["Stellenbosch"]


def test_embed_url_place_chain_route_view():
    mod = _load()
    ps = [{"name": "A", "coords": "", "query": "A"},
          {"name": "B", "coords": "", "query": "B"},
          {"name": "C", "coords": "", "query": "C"}]
    url, mode = mod._embed_url("K", ps[:1], None, True, "", None)
    assert mode == "place" and "/place?" in url and "q=A" in url
    url, mode = mod._embed_url("K", ps, None, True, "", None)
    assert mode == "directions"
    q = _qs(url)
    assert q["origin"] == ["A"] and q["destination"] == ["C"]
    assert q["waypoints"] == ["B"]
    url, mode = mod._embed_url("K", ps, None, False, "", None)
    assert mode == "place"  # chain='no' pins the first only
    r = {"origin": ps[0], "destination": ps[2], "waypoints": [ps[1]],
         "mode": "walking"}
    url, mode = mod._embed_url("K", [], r, True, "", None)
    assert mode == "directions" and "mode=walking" in url
    url, mode = mod._embed_url("K", [], None, True, "1.0,2.0", 12)
    assert mode == "view" and "center=1.0%2C2.0" in url


def test_static_google_markers_and_paths():
    mod = _load()
    ps = [{"name": "A", "coords": "1.0,2.0", "query": "1.0,2.0"},
          {"name": "B", "coords": "", "query": "Stellenbosch"}]
    url = mod._static_google("K", ps, None, "", "640x360", None, "",
                             "roadmap")
    markers = _qs(url)["markers"]
    assert len(markers) == 2
    assert "label:A|1.0,2.0" in markers[0]
    assert markers[1].endswith("|Stellenbosch")
    r = {"origin": ps[0], "destination": ps[1], "waypoints": [],
         "mode": "driving"}
    url = mod._static_google("K", ps, r, "abc~DEF", "640x360", None, "",
                             "roadmap")
    assert "enc%3Aabc~DEF" in url or "enc:abc~DEF" in _qs(url)["path"][0]
    url2 = mod._static_google("K", ps, r, "", "640x360", None, "",
                              "roadmap")
    path = _qs(url2)["path"][0]
    assert "Stellenbosch" in path and "enc:" not in path


def test_static_osm_markers_center_zoom():
    mod = _load()
    url = mod._static_osm(["-33.92,18.42", "-33.93,18.86"], "640x360",
                          None)
    q = _qs(url)
    assert q["markers"] == ["-33.92,18.42,red-pushpin",
                            "-33.93,18.86,red-pushpin"]
    assert "center" in q and q["size"] == ["640x360"]
    assert q["zoom"] == ["11"]  # ~0.44° lon span -> cap 0.5 -> z11
    url = mod._static_osm(["-33.9,18.4", "10.0,99.0"], "640x360", 8)
    assert _qs(url)["zoom"] == ["8"]  # explicit wins


# ----------------------------------------------------------------- run()

def test_run_interactive_no_key_is_honest(monkeypatch):
    mod = _load()
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    out = asyncio.run(mod.run(
        None, kind="interactive",
        places=[{"name": "Cape Town", "lat": -33.92, "lon": 18.42}]))
    assert not out["ok"] and out["needs_key"]
    assert "maps/search" in out["open_url"]
    assert "staticmap.openstreetmap.de" in out["static_fallback"]
    assert "kind='static'" in out["error"]


def test_run_interactive_place_and_chain(monkeypatch):
    mod = _load()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "TESTKEY")
    out = asyncio.run(mod.run(
        None, kind="interactive", places=[{"name": "Cape Town"}]))
    assert out["ok"] and "/place?" in out["embed_url"]
    assert "<iframe" in out["iframe_html"] and "TESTKEY" in out["embed_url"]
    assert "Open in Google Maps" in out["markdown"]
    out = asyncio.run(mod.run(
        None, kind="interactive",
        places=[{"name": "A"}, {"name": "B"}, {"name": "C"}]))
    assert "/directions?" in out["embed_url"]
    assert any("chained" in w for w in out["warnings"])


def test_run_interactive_route_plus_places_warns(monkeypatch):
    mod = _load()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "TESTKEY")
    out = asyncio.run(mod.run(
        None, kind="interactive",
        places=[{"name": "Side Stop"}],
        route={"origin": "Cape Town", "destination": "Paarl"}))
    assert out["ok"] and "/directions?" in out["embed_url"]
    assert any("not drawn" in w for w in out["warnings"])


def test_run_static_google_route_polyline(monkeypatch):
    mod = _load()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "TESTKEY")
    calls = _patch_httpx(monkeypatch, mod, [
        ("routes.googleapis.com", _Resp(payload={
            "routes": [{"distanceMeters": 145000,
                        "duration": "6300s",
                        "polyline": {"encodedPolyline": "abc~XYZ"}}]})),
    ])
    out = asyncio.run(mod.run(
        None, kind="static",
        route={"origin": "Cape Town",
               "destination": "Port Elizabeth",
               "waypoints": [{"name": "George"}]}))
    assert out["ok"] and out["provider"] == "google"
    assert "maps/api/staticmap" in out["image_url"]
    assert "enc%3Aabc~XYZ" in out["image_url"] or \
        "enc:abc~XYZ" in out["image_url"]
    assert out["distance_km"] == 145.0 and out["duration_min"] == 105
    post = [c for c in calls if c[0] == "post"][0]
    body = post[2]
    assert body["travelMode"] == "DRIVE"
    assert body["intermediates"] == [{"address": "George"}]
    assert body["origin"] == {"address": "Cape Town"}


def test_run_static_google_straightline_fallback(monkeypatch):
    mod = _load()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "TESTKEY")
    _patch_httpx(monkeypatch, mod, [])  # Routes POST raises
    out = asyncio.run(mod.run(
        None, kind="static",
        route={"origin": "Cape Town", "destination": "Paarl"}))
    assert out["ok"] and "maps/api/staticmap" in out["image_url"]
    assert any("straight line" in w for w in out["warnings"])
    assert "distance_km" not in out


def test_run_static_keyless_osm_with_coords(monkeypatch):
    mod = _load()
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    out = asyncio.run(mod.run(
        None, kind="static",
        places=[{"name": "CPT", "lat": -33.92, "lon": 18.42},
                {"name": "Stell", "lat": -33.93, "lon": 18.86}]))
    assert out["ok"] and out["provider"] == "osm"
    assert "staticmap.openstreetmap.de" in out["image_url"]
    assert out["image_url"].count("markers=") == 2
    assert "![" in out["markdown"] and "openstreetmap" in out["image_url"]
    assert "GOOGLE_MAPS_API_KEY" in out["note"]


def test_run_static_keyless_geocodes_names(monkeypatch):
    mod = _load()
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    calls = _patch_httpx(monkeypatch, mod, [
        ("nominatim", _Resp(payload=[{"lat": "-33.9249",
                                      "lon": "18.4241"}])),
    ])
    out = asyncio.run(mod.run(
        None, kind="static", places=[{"name": "Cape Town"},
                                     {"name": "Nowhere"}]))
    assert out["ok"] and out["provider"] == "osm"
    assert "-33.924900%2C18.424100" in out["image_url"] or \
        "-33.924900,18.424100" in out["image_url"]
    assert any("nominatim" in c[1] for c in calls)


def test_run_static_keyless_route_warns_no_line(monkeypatch):
    mod = _load()
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    _patch_httpx(monkeypatch, mod, [
        ("nominatim", _Resp(payload=[{"lat": "-33.9", "lon": "18.4"}])),
    ])
    out = asyncio.run(mod.run(
        None, kind="static",
        route={"origin": "Cape Town", "destination": "Paarl"}))
    assert out["ok"] and out["provider"] == "osm"
    assert any("route" in w for w in out["warnings"])


def test_run_static_keyless_nothing_resolves(monkeypatch):
    mod = _load()
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    _patch_httpx(monkeypatch, mod, [
        ("nominatim", _Resp(payload=[])),
    ])
    out = asyncio.run(mod.run(None, kind="static",
                              places=[{"name": "Unfindable Place"}]))
    assert not out["ok"] and "open_url" in out
    assert "no key and no coordinates" in out["error"]


def test_run_validation_errors():
    mod = _load()
    out = asyncio.run(mod.run(None))
    assert not out["ok"] and "places" in out["error"]
    out = asyncio.run(mod.run(None, kind="3d",
                              places=[{"name": "X"}]))
    assert not out["ok"] and "kind" in out["error"]
    out = asyncio.run(mod.run(
        None, places=[{"name": str(i)} for i in range(11)]))
    assert not out["ok"] and "capped" in out["error"]


def test_run_center_view(monkeypatch):
    mod = _load()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "TESTKEY")
    out = asyncio.run(mod.run(None, kind="interactive",
                              center="-33.9,18.4", zoom=11))
    assert out["ok"] and out["mode"] == "view"
    assert "zoom=11" in out["embed_url"]


# ----------------------------------------------------------- drop registry

def test_manifest_fragment_matches_declaration():
    mod = _load()
    frag = yaml.safe_load(MANIFEST.read_text())
    entry = frag["tools"]["map_embed"] if "tools" in frag \
        else frag["map_embed"]
    assert entry["module"] == "map_embed"
    assert entry["policy"] == "read"
    assert mod.DECLARATION["name"] == "map_embed"
    props = mod.DECLARATION["parameters"]["properties"]
    assert {"places", "route", "kind"} <= set(props)
    assert len(mod.DECLARATION["description"]) <= 300


def test_tool_guide_fragment_has_key():
    frag = yaml.safe_load(GUIDE.read_text())
    assert "map_embed" in frag
    assert "open_url" in frag["map_embed"]


def test_scenario_references_tool():
    scen = yaml.safe_load(SCENARIO.read_text())
    text = SCENARIO.read_text()
    assert "map_embed" in text
    assert scen["turns"][0]["expect"]["calls_any"] == ["map_embed"]
