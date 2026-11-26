"""Unit tests for the kk_places drop staged under
integrations/ada-voice/ (card kk-places-tool / OPS-0506, 2026-11-26).

No-network adapter suite — same harness as test_place_report_drop.py /
test_map_embed_drop.py: the module is loaded standalone, httpx.AsyncClient
is replaced by a routing fake (Places API New searchText POST +
places/{id} GET), and runner.cms_publish_page is a recording fake.
Covers the keyless needs_key fork, empty-results honesty, the
public/confirmed gate, dossier publish failure, and the manifest /
tool_guide / scenario registry fragments.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
TOOL = DROP / "backend" / "tools.d" / "kk_places.py"
MANIFEST = DROP / "backend" / "tools.d" / "manifest.kk_places.yml"
GUIDE = DROP / "backend" / "tool_guide.kk_places.yml"
SCENARIO = DROP / "tests" / "scenarios-live" / "kk_places.yaml"


def _load():
    spec = importlib.util.spec_from_file_location("kk_places", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _HttpError(Exception):
    def __init__(self, resp):
        self.response = resp
        super().__init__(f"HTTP {resp.status_code}")


class _Resp:
    def __init__(self, payload=None, status_code=200, url=""):
        self._payload = payload
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _HttpError(self)
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """httpx.AsyncClient stand-in — routes GETs and POSTs on the
    request URL; records (method, url, params|json) for assertions."""

    def __init__(self, routes, calls, *a, **kw):
        self._routes = routes
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _route(self, method, url, payload):
        self._calls.append((method, str(url), payload))
        for pat, resp in self._routes:
            if pat in str(url):
                return resp
        raise RuntimeError(f"unstubbed {method} {url}")

    async def get(self, url, params=None, headers=None):
        return self._route("get", url, params)

    async def post(self, url, json=None, headers=None):
        return self._route("post", url, json)


def _patch_httpx(monkeypatch, mod, routes):
    calls = []

    def _client(*a, **kw):
        return _FakeClient(routes, calls)

    from types import SimpleNamespace
    monkeypatch.setattr(mod, "httpx",
                        SimpleNamespace(AsyncClient=_client))
    return calls


def _key(monkeypatch):
    monkeypatch.setenv("ADA_PLACES_API_KEY", "TESTPLACEKEY")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)


class _Runner:
    def __init__(self, fail=False):
        self.pub_calls = []
        self.fail = fail

    async def cms_publish_page(self, **kw):
        self.pub_calls.append(kw)
        if self.fail:
            raise RuntimeError("mddb down")
        return {"status": "ok",
                "view_url": f"/cms/{kw['slug']}",
                "public_url": ""}


def _place_payload(**over):
    p = {
        "id": "ChIJtestplace123",
        "displayName": {"text": "JJ&J Bistro Cafe and Bar",
                        "languageCode": "en"},
        "formattedAddress": "3302 Bangkok, Thailand",
        "location": {"latitude": 13.7563, "longitude": 100.5018},
        "internationalPhoneNumber": "+66 2 000 0000",
        "websiteUri": "https://example.com",
        "rating": 4.5,
        "userRatingCount": 321,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "types": ["restaurant", "food", "point_of_interest",
                  "establishment"],
        "googleMapsUri": "https://maps.google.com/?cid=123",
        "businessStatus": "OPERATIONAL",
        "currentOpeningHours": {
            "openNow": True,
            "weekdayDescriptions": ["Monday: 08:00–22:00",
                                    "Tuesday: 08:00–22:00"]},
    }
    p.update(over)
    return p


# ------------------------------------------------------------- pure helpers

def test_slug_for_deterministic_and_prefixed():
    mod = _load()
    p = {"name": "JJ&J Bistro Café", "place_id": "ChIJabc",
         "coords": "13.7,100.5", "address": "Bangkok"}
    s1 = mod._slug_for(p)
    s2 = mod._slug_for(dict(p))
    assert s1 == s2 and s1.startswith("place-")
    assert all(c.isascii() and (c.isalnum() or c == "-") for c in s1)
    # Thai-only name falls back through address/coords, never empty
    p2 = {"name": "ร้านกาแฟ", "place_id": "", "coords": "",
          "address": ""}
    s3 = mod._slug_for(p2)
    assert s3.startswith("place-") and len(s3) > len("place-")


def test_norm_maps_fields():
    mod = _load()
    n = mod._norm(_place_payload(), "2026-11-26T00:00:00+00:00")
    assert n["name"] == "JJ&J Bistro Cafe and Bar"
    assert n["place_id"] == "ChIJtestplace123"
    assert n["coords"] == "13.756300,100.501800"
    assert n["phone"] == "+66 2 000 0000"
    assert n["rating"] == 4.5 and n["ratings_count"] == 321
    assert n["price_level"] == "$$"
    assert n["open_now"] is True
    assert n["hours"] == ["Monday: 08:00–22:00",
                          "Tuesday: 08:00–22:00"]
    assert n["business_status"] == "OPERATIONAL"


def test_norm_missing_optionals_stay_empty():
    mod = _load()
    n = mod._norm({"id": "x", "displayName": {"text": "Nameless"}},
                  "ts")
    assert n["coords"] == "" and n["phone"] == ""
    assert n["open_now"] is None and n["hours"] == []
    assert n["price_level"] == ""


def test_verdict_branches():
    mod = _load()
    base = {"business_status": "OPERATIONAL", "open_now": True,
            "hours": []}
    assert "Open now" in mod._verdict(base, "en")
    assert "เปิดอยู่" in mod._verdict(base, "th")
    assert "Closed now" in mod._verdict(
        {**base, "open_now": False}, "en")
    assert "Permanently closed" in mod._verdict(
        {**base, "business_status": "CLOSED_PERMANENTLY"}, "en")
    assert "Temporarily closed" in mod._verdict(
        {**base, "business_status": "CLOSED_TEMPORARILY"}, "en")
    assert "unknown" in mod._verdict(
        {**base, "open_now": None}, "en")


def test_page_has_dossier_shape():
    mod = _load()
    place = mod._norm(_place_payload(), "2026-11-26T01:02:03+00:00")
    title, body = mod._page(place, "jj&j bistro", "en", "kk")
    assert "JJ&J Bistro" in title
    assert "Open now" in body
    assert "Monday: 08:00" in body
    assert "+66 2 000 0000" in body
    assert "google-places" in body and "kk via" in body
    assert "place_id: ChIJtestplace123" in body


# ----------------------------------------------------------------- run()

def test_run_search_full_flow_private_dossier(monkeypatch):
    mod = _load()
    _key(monkeypatch)
    calls = _patch_httpx(monkeypatch, mod, [
        ("places:searchText", _Resp(payload={"places": [
            _place_payload()]})),
    ])
    runner = _Runner()
    out = asyncio.run(mod.run(
        runner, query="JJ&J Bistro Bangkok", lang="en"))
    assert out["ok"] and out["count"] == 1
    best = out["best"]
    assert best["name"] == "JJ&J Bistro Cafe and Bar"
    assert best["open_now"] is True
    assert out["maps_url"].startswith("https://maps.google.com")
    # one POST to searchText carrying the query + field mask header path
    post = [c for c in calls if c[0] == "post"][0]
    assert "JJ&J Bistro Bangkok" in str(post[2]["textQuery"])
    # dossier published PRIVATE by default
    assert len(runner.pub_calls) == 1
    pub = runner.pub_calls[0]
    assert pub["public"] == "false"
    assert pub["domain"] == "places" and pub["fresh_for"] == "7d"
    assert pub["slug"].startswith("place-")
    assert out["dossier"]["ok"] and out["dossier"]["slug"] == pub["slug"]
    assert "checked_at" in out and out["checked_at"].endswith("+00:00")


def test_run_search_location_bias(monkeypatch):
    mod = _load()
    _key(monkeypatch)
    calls = _patch_httpx(monkeypatch, mod, [
        ("places:searchText", _Resp(payload={"places": []})),
    ])
    out = asyncio.run(mod.run(
        _Runner(), query="cafe", lat=13.7, lon=100.5))
    post = [c for c in calls if c[0] == "post"][0]
    bias = post[2]["locationBias"]["circle"]
    assert bias["center"] == {"latitude": 13.7, "longitude": 100.5}
    assert bias["radius"] == 2000.0
    # empty result is an honest answer, not an error
    assert out["ok"] and out["places"] == [] and out["count"] == 0
    assert "maps/search" in out["maps_url"]
    assert "NOT written" in out["note"]


def test_run_place_id_details_path(monkeypatch):
    mod = _load()
    _key(monkeypatch)
    calls = _patch_httpx(monkeypatch, mod, [
        ("places/ChIJtestplace123", _Resp(payload=_place_payload())),
    ])
    runner = _Runner()
    out = asyncio.run(mod.run(
        runner, place_id="ChIJtestplace123", lang="en"))
    assert out["ok"] and out["count"] == 1
    assert out["place_id"] == "ChIJtestplace123"
    get = [c for c in calls if c[0] == "get"][0]
    assert "ChIJtestplace123" in get[1]
    assert runner.pub_calls[0]["slug"].startswith("place-")


def test_run_no_key_needs_key(monkeypatch):
    mod = _load()
    monkeypatch.delenv("ADA_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    runner = _Runner()
    out = asyncio.run(mod.run(runner, query="Some Cafe"))
    assert not out["ok"] and out["needs_key"]
    assert "maps/search" in out["maps_url"]
    assert "never invent" in out["error"]
    assert runner.pub_calls == []  # nothing looked up, nothing saved


def test_run_google_maps_key_fallback(monkeypatch):
    mod = _load()
    monkeypatch.delenv("ADA_PLACES_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "GMAPSKEY")
    calls = _patch_httpx(monkeypatch, mod, [
        ("places:searchText", _Resp(payload={"places": [_place_payload()]})),
    ])
    out = asyncio.run(mod.run(_Runner(), query="x"))
    assert out["ok"] and out["count"] == 1
    assert calls  # the fallback key drove the call


def test_run_validation_no_input():
    mod = _load()
    out = asyncio.run(mod.run(_Runner()))
    assert not out["ok"] and "query=" in out["error"]


def test_run_api_error_permission_denied(monkeypatch):
    mod = _load()
    _key(monkeypatch)
    _patch_httpx(monkeypatch, mod, [
        ("places:searchText", _Resp(
            payload={"error": {"code": 403,
                               "status": "PERMISSION_DENIED",
                               "message": "Places API has not been "
                                          "used in project"}},
            status_code=403)),
    ])
    out = asyncio.run(mod.run(_Runner(), query="x"))
    assert not out["ok"]
    assert "Places API" in out["error"] and "ADA_PLACES_API_KEY" in out["error"]


def test_run_publish_failure_keeps_lookup(monkeypatch):
    """The lookup answer survives a dossier write failure — the page is
    the artifact, not the reply; the model is told not to claim it."""
    mod = _load()
    _key(monkeypatch)
    _patch_httpx(monkeypatch, mod, [
        ("places:searchText", _Resp(payload={"places": [_place_payload()]})),
    ])
    out = asyncio.run(mod.run(
        _Runner(fail=True), query="JJ&J", lang="en"))
    assert out["ok"] and out["count"] == 1
    assert out["dossier"]["ok"] is False
    assert "did NOT save" in out["note"]


def test_run_public_requires_confirmed(monkeypatch):
    mod = _load()
    _key(monkeypatch)
    _patch_httpx(monkeypatch, mod, [
        ("places:searchText", _Resp(payload={"places": [_place_payload()]})),
    ])
    runner = _Runner()
    out = asyncio.run(mod.run(
        runner, query="x", public="yes", lang="en"))
    # saved PRIVATE — public never silently upgrades
    assert runner.pub_calls[0]["public"] == "false"
    assert "confirmed='yes'" in out["note"]
    out2 = asyncio.run(mod.run(
        _Runner(), query="x", public="yes", confirmed="yes", lang="en"))
    assert out2["ok"]


def test_run_public_confirmed_publishes_public(monkeypatch):
    mod = _load()
    _key(monkeypatch)
    _patch_httpx(monkeypatch, mod, [
        ("places:searchText", _Resp(payload={"places": [_place_payload()]})),
    ])
    runner = _Runner()
    out = asyncio.run(mod.run(
        runner, query="x", public="yes", confirmed="yes", lang="en"))
    assert out["ok"]
    assert runner.pub_calls[0]["public"] == "true"


def test_lane_footer_from_collection_env(monkeypatch):
    mod = _load()
    monkeypatch.setenv("ADA_CMS_COLLECTION", "ada-cms-pages-kk")
    assert mod._lane() == "kk"
    monkeypatch.setenv("ADA_CMS_COLLECTION", "ada-cms-pages")
    assert mod._lane() == "tony"
    monkeypatch.delenv("ADA_CMS_COLLECTION", raising=False)
    assert mod._lane() == ""


# ----------------------------------------------------------- drop registry

def test_manifest_fragment_matches_declaration():
    mod = _load()
    frag = yaml.safe_load(MANIFEST.read_text())
    tools = frag.get("tools", frag)
    entry = tools["kk_places"]
    assert entry["module"] == "kk_places"
    assert entry["policy"] == "read"
    assert mod.DECLARATION["name"] == "kk_places"
    props = mod.DECLARATION["parameters"]["properties"]
    assert {"query", "place_id", "lat", "lon", "public",
            "confirmed"} <= set(props)
    assert len(mod.DECLARATION["description"]) <= 300


def test_tool_guide_fragment_has_key():
    frag = yaml.safe_load(GUIDE.read_text())
    assert "kk_places" in frag
    assert "checked_at" in frag["kk_places"] or \
        "checked" in frag["kk_places"]


def test_scenario_references_tool():
    scen = yaml.safe_load(SCENARIO.read_text())
    assert scen["name"] == "kk-places"
    assert "kk_places" in SCENARIO.read_text()
    assert scen["turns"][0]["expect"]["calls_any"] == ["kk_places"]
