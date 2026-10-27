"""Verification for the wp_read + wp_update drops staged under
integrations/ada-voice/ (card line-wp-site-manager — P2 read-only
browse/preview, P3 confirm-gated update/publish).

Same harness shape as test_cpt_post_drop.py: each tools.d module is
loaded standalone with stubbed backend.wp_client + httpx — the module
under test is the only real code in play.

- wp_read: action/list/get guards, list param shape (status, per_page,
  search, member-tag resolution via read-only GET tags — never the
  tag-creating ensure_tag), get-by-id and get-by-slug paths, draft
  preview note.
- wp_update: guards (posts/pages only — CPT records stay with their
  writers; nothing-to-change), the GET-before-POST transition report
  (draft -> publish), 404 honesty, payload scoping (only the fields
  asked for), trash mapping.

No patches to apply — both files are NEW tools.d modules; the
manifest/tool_guide fragments are checked for shape + the confirmed
policy that the dispatch layer enforces.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types as pytypes
from pathlib import Path
from types import SimpleNamespace

import yaml

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
READ_TOOL = DROP / "backend" / "tools.d" / "wp_read.py"
UPDATE_TOOL = DROP / "backend" / "tools.d" / "wp_update.py"
READ_MANIFEST = DROP / "backend" / "tools.d" / "manifest.wp_read.yml"
UPDATE_MANIFEST = DROP / "backend" / "tools.d" / "manifest.wp_update.yml"
READ_GUIDE = DROP / "backend" / "tool_guide.wp_read.yml"
UPDATE_GUIDE = DROP / "backend" / "tool_guide.wp_update.yml"

ENV = {"WP_SITE_URL": "https://x.test/wp", "WP_APP_USER": "u",
       "WP_APP_PASSWORD": "p"}

POST = {
    "id": 21, "type": "post", "status": "draft",
    "slug": "hello-world-2",
    "date": "2026-10-14T10:00:00", "modified": "2026-10-15T09:00:00",
    "link": "https://x.test/wp/index.php/hello-world-2/",
    "title": {"rendered": "Hello <b>World</b>"},
    "content": {"rendered": "<p>Line one</p>\n<p>Line two</p>"},
}


class _Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = "" if isinstance(self._data, (dict, list)) else str(
            self._data)

    def json(self):
        return self._data


class _FakeAsyncClient:
    """Tools build httpx.AsyncClient but only pass the handle to the
    (stubbed) wp functions — a stand-in context manager suffices."""

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _stub_httpx(monkeypatch):
    mod = pytypes.ModuleType("httpx")
    mod.AsyncClient = _FakeAsyncClient
    monkeypatch.setitem(sys.modules, "httpx", mod)


def _load_tool(monkeypatch, path: Path, api_router):
    """Import a tools.d module standalone: stub backend.wp_client
    (+ httpx); api_router(method, route, kw) -> _Resp decides each
    REST call."""
    _stub_httpx(monkeypatch)

    calls = []

    async def api(client, env, method, route, **kw):
        calls.append((method, route, kw))
        return api_router(method, route, kw)

    wp = pytypes.ModuleType("backend.wp_client")
    wp.PEOPLE = ("tony", "kk", "nhong")
    wp.PUBLIC_BASE = "https://x.test/wp"
    wp.env = lambda: ENV
    wp.configured = lambda e: all(
        e.get(k) for k in ("WP_SITE_URL", "WP_APP_USER",
                           "WP_APP_PASSWORD"))
    wp.api = api
    wp.api_calls = calls
    wp.paragraphs = lambda t: "".join(
        f"<p>{ln}</p>\n" for ln in t.split("\n") if ln.strip())
    wp.https = lambda u: u

    backend = sys.modules.get("backend") or pytypes.ModuleType("backend")
    backend.__path__ = []
    backend.wp_client = wp
    monkeypatch.setitem(sys.modules, "backend", backend)
    monkeypatch.setitem(sys.modules, "backend.wp_client", wp)

    spec = importlib.util.spec_from_file_location(
        f"tools_d.{path.stem}_chaba_{id(wp)}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, wp


def _runner(instance="kk"):
    r = SimpleNamespace(instance=instance)
    r._memory_identity = lambda: None
    return r


def _run(mod, **args):
    return asyncio.run(mod.run(_runner(), **args))


def _router_ok(method, route, kw):
    return _Resp(200, POST if not route.endswith("/tags") else
                 [{"id": 7, "slug": "kk"}])


# ------------------------------------------------------------- wp_read

def test_read_guards(monkeypatch):
    mod, _ = _load_tool(monkeypatch, READ_TOOL, _router_ok)
    res = _run(mod, action="bogus")
    assert res["ok"] is False and "action" in res["error"]
    res = _run(mod, action="list", post_type="bad type!")
    assert res["ok"] is False and "post_type" in res["error"]
    res = _run(mod, action="list", status="bogus")
    assert res["ok"] is False and "status" in res["error"]
    res = _run(mod, action="list", person="nobody")
    assert res["ok"] is False and "person" in res["error"]
    res = _run(mod, action="list", person="kk", post_type="expense")
    assert res["ok"] is False and "saved_by" in res["error"]
    res = _run(mod, action="get")
    assert res["ok"] is False and "id" in res["error"]


def test_read_list_shape(monkeypatch):
    captured = []

    def router(method, route, kw):
        captured.append((method, route, kw))
        return _Resp(200, [POST])

    mod, _ = _load_tool(monkeypatch, READ_TOOL, router)
    res = _run(mod, action="list", status="draft", search="hello",
               limit=5)
    assert res["ok"] and res["count"] == 1
    row = res["items"][0]
    assert row["id"] == 21 and row["title"] == "Hello World"
    assert row["status"] == "draft"
    method, route, kw = captured[0]
    assert (method, route) == ("GET", "posts")
    assert kw["params"]["status"] == "draft"
    assert kw["params"]["per_page"] == 5
    assert kw["params"]["search"] == "hello"


def test_read_list_person_resolves_tag_readonly(monkeypatch):
    """person= must GET tags, never wp.ensure_tag — a read tool that
    mints tags on the site is a write."""
    captured = []

    def router(method, route, kw):
        captured.append((method, route, kw))
        if route == "tags":
            return _Resp(200, [{"id": 7, "slug": "kk"}])
        return _Resp(200, [POST])

    mod, _ = _load_tool(monkeypatch, READ_TOOL, router)
    res = _run(mod, action="list", person="kk")
    assert res["ok"]
    assert all(m == "GET" for m, _r, _k in captured)
    list_call = [c for c in captured if c[1] == "posts"][0]
    assert list_call[2]["params"]["tags"] == 7


def test_read_list_bad_type_propagates_error(monkeypatch):
    mod, _ = _load_tool(monkeypatch, READ_TOOL,
                        lambda m, r, k: _Resp(403, {"code": "x"}))
    res = _run(mod, action="list", post_type="lesson")
    assert res["ok"] is False and "403" in res["error"]


def test_read_get_by_id_preview(monkeypatch):
    mod, _ = _load_tool(monkeypatch, READ_TOOL, _router_ok)
    res = _run(mod, action="get", id=21)
    assert res["ok"] and res["id"] == 21
    assert res["title"] == "Hello World"
    assert "Line one" in res["content"] and "<p>" not in res["content"]
    # draft -> the text IS the member preview + publish hint
    assert res["status"] == "draft"
    assert res["note"] and "wp_update" in res["note"]


def test_read_get_by_slug_status_any(monkeypatch):
    captured = []

    def router(method, route, kw):
        captured.append((method, route, kw))
        return _Resp(200, [POST])

    mod, _ = _load_tool(monkeypatch, READ_TOOL, router)
    res = _run(mod, action="get", slug="hello-world-2")
    assert res["ok"] and res["id"] == 21
    _m, _r, kw = captured[0]
    assert kw["params"]["slug"] == "hello-world-2"
    assert kw["params"]["status"] == "any"


def test_read_get_slug_miss(monkeypatch):
    mod, _ = _load_tool(monkeypatch, READ_TOOL,
                        lambda m, r, k: _Resp(200, []))
    res = _run(mod, action="get", slug="nope")
    assert res["ok"] is False and "no posts entry" in res["error"]


def test_read_get_truncates_and_full(monkeypatch):
    long_post = dict(POST, status="publish",
                     content={"rendered": "<p>" + "x" * 2000 + "</p>"})
    mod, _ = _load_tool(monkeypatch, READ_TOOL,
                        lambda m, r, k: _Resp(200, long_post))
    res = _run(mod, action="get", id=21)
    assert res["ok"] and res["truncated"]
    assert len(res["content"]) <= 1300
    assert res["note"] is None  # published -> no draft note
    res = _run(mod, action="get", id=21, full=True)
    assert res["ok"] and not res["truncated"]
    assert len(res["content"]) >= 2000


# ----------------------------------------------------------- wp_update

def test_update_guards(monkeypatch):
    mod, _ = _load_tool(monkeypatch, UPDATE_TOOL, _router_ok)
    res = _run(mod)
    assert res["ok"] is False and "id required" in res["error"]
    res = _run(mod, id=21, post_type="expense", title="x")
    assert res["ok"] is False and "posts/pages" in res["error"]
    res = _run(mod, id=21, status="bogus")
    assert res["ok"] is False and "status" in res["error"]
    res = _run(mod, id=21)
    assert res["ok"] is False and "nothing to change" in res["error"]


def test_update_404_honest_miss(monkeypatch):
    mod, _ = _load_tool(monkeypatch, UPDATE_TOOL,
                        lambda m, r, k: _Resp(404, {"code": "rest_post_invalid_id"}))
    res = _run(mod, id=999, status="publish")
    assert res["ok"] is False and "no posts entry" in res["error"]


def test_update_publish_transition(monkeypatch):
    """Draft -> publish: GET first (prev status for the report), then
    POST {status: publish} only — no title/content smuggling."""
    posted = []

    def router(method, route, kw):
        if method == "GET":
            return _Resp(200, dict(POST, status="draft"))
        posted.append(kw.get("json"))
        return _Resp(200, dict(POST, status="publish"))

    mod, _ = _load_tool(monkeypatch, UPDATE_TOOL, router)
    res = _run(mod, id=21, status="publish", confirmed=True)
    assert res["ok"] and res["status"] == "publish"
    assert res["transition"] == "draft -> publish"
    assert posted == [{"status": "publish"}]
    assert "live" in res["note"]


def test_update_retitle_scope(monkeypatch):
    posted = []

    def router(method, route, kw):
        if method == "GET":
            return _Resp(200, dict(POST, status="publish"))
        posted.append((route, kw.get("json")))
        return _Resp(200, dict(POST, status="publish",
                               title={"rendered": "New title"}))

    mod, _ = _load_tool(monkeypatch, UPDATE_TOOL, router)
    res = _run(mod, id=21, title="New title")
    assert res["ok"] and res["title"] == "New title"
    assert res["prev_title"] == "Hello World"
    assert res["transition"] is None  # no status move requested
    route, payload = posted[0]
    assert route == "posts/21"
    assert payload == {"title": "New title"}  # only what was asked


def test_update_content_wrapped(monkeypatch):
    posted = []

    def router(method, route, kw):
        if method == "GET":
            return _Resp(200, POST)
        posted.append(kw.get("json"))
        return _Resp(200, POST)

    mod, _ = _load_tool(monkeypatch, UPDATE_TOOL, router)
    res = _run(mod, id=21, content="one\ntwo")
    assert res["ok"]
    assert posted[0]["content"] == "<p>one</p>\n<p>two</p>\n"


def test_update_trash_note(monkeypatch):
    def router(method, route, kw):
        if method == "GET":
            return _Resp(200, dict(POST, status="publish"))
        return _Resp(200, dict(POST, status="trash"))

    mod, _ = _load_tool(monkeypatch, UPDATE_TOOL, router)
    res = _run(mod, id=21, status="trash")
    assert res["ok"] and res["transition"] == "publish -> trash"
    assert "restorable" in res["note"]


def test_update_pages_route(monkeypatch):
    seen = []

    def router(method, route, kw):
        seen.append((method, route))
        return _Resp(200, dict(POST, type="page", status="publish"))

    mod, _ = _load_tool(monkeypatch, UPDATE_TOOL, router)
    res = _run(mod, id=10, post_type="pages", status="private")
    assert res["ok"]
    assert ("GET", "pages/10") in seen and ("POST", "pages/10") in seen


# ------------------------------------------- manifest + guide fragments

def test_manifest_fragments():
    read = yaml.safe_load(READ_MANIFEST.read_text())
    upd = yaml.safe_load(UPDATE_MANIFEST.read_text())
    assert read["tools"]["wp_read"]["module"] == "wp_read"
    assert read["tools"]["wp_read"]["policy"] == "read"
    assert read["tools"]["wp_read"]["secondary_allowed"] is True
    # P3 confirm-before-publish rides the dispatch gate — the manifest
    # is what turns it on; a 'read' policy here would silently ship an
    # ungated writer.
    assert upd["tools"]["wp_update"]["module"] == "wp_update"
    assert upd["tools"]["wp_update"]["policy"] == "confirmed"


def test_declarations(monkeypatch):
    """tools_loader contract: DECLARATION name matches, non-empty
    description, parameters object. wp_update declares `confirmed` as
    a property (never required — the dispatch gate pops it before
    schema validation runs)."""
    for path, name in ((READ_TOOL, "wp_read"), (UPDATE_TOOL, "wp_update")):
        mod, _ = _load_tool(monkeypatch, path, _router_ok)
        decl = mod.DECLARATION
        assert decl["name"] == name
        assert isinstance(decl["description"], str) and decl["description"]
        params = decl["parameters"]
        assert params["type"] == "object" and params["properties"]
    upd_mod, _ = _load_tool(monkeypatch, UPDATE_TOOL, _router_ok)
    props = upd_mod.DECLARATION["parameters"]["properties"]
    assert "confirmed" in props
    assert "confirmed" not in upd_mod.DECLARATION["parameters"].get(
        "required", [])


def test_guide_fragments():
    read_guide = READ_GUIDE.read_text()
    upd_guide = UPDATE_GUIDE.read_text()
    assert "\nwp_read:" in "\n" + read_guide
    assert "\nwp_update:" in "\n" + upd_guide
    assert "confirmed=true" in upd_guide
    assert "wp_update" in read_guide  # preview -> publish handoff
