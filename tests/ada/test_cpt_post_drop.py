"""Verification for the cpt_post drop staged under
integrations/ada-voice/ (card line-cpt-writer-router — LINE save-asks
route to the right chaba-boards CPT + registered meta).

Two halves, same shape as test_line_file_doc_ingest.py:

- cpt_post (backend/tools.d/cpt_post.py) — loaded standalone with
  stubbed backend.wp_client + httpx, exercised end to end: kind
  routing, title standard, meta scoping + saved_by, person defaulting
  (kk lane -> kk — "KK is boss of kk-hom"), contact/asset slug upsert,
  and the plugin-skew meta retry (chaba-boards <0.5.1 lacks saved_by —
  a meta 400 must not lose the record).

- patch set — wp_client slug support, wp_post description/guide
  reroute, tool-surface coverage_debt — applied to a copy of the
  ada-voice checkout (ADA_PI env or ~/CascadeProjects/ada-voice);
  skips when no checkout is reachable.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import types as pytypes
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tests.ada._drops import check_patch, drop_guard_ok

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
TOOL = DROP / "backend" / "tools.d" / "cpt_post.py"
PATCHES = [
    "backend/wp_client.cpt-post.patch",
    "backend/tools.d/wp_post.cpt-router.patch",
    "backend/tool_guide.cpt-router.patch",
    "ssot.tool-surface.cpt-post.patch",
]
ADA_PI = Path(os.environ.get("ADA_PI",
                             str(Path.home() / "CascadeProjects" / "ada-voice")))

ENV = {"WP_SITE_URL": "https://x.test/wp", "WP_APP_USER": "u",
       "WP_APP_PASSWORD": "p"}


class _AsyncRecorder:
    """Async callable recording its calls — enough mock for the wp
    seams without pulling unittest.mock in."""

    def __init__(self, result=None):
        self.result = result
        self.calls = []

    async def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        r = self.result
        return r() if callable(r) else r


class _FakeAsyncClient:
    """cpt_post builds httpx.AsyncClient but only passes the handle to
    the (stubbed) wp functions — a stand-in context manager suffices."""

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


def _load_tool(monkeypatch):
    """Import cpt_post standalone: stub backend.wp_client (+ httpx) so
    the module under test is the only real code in play."""
    _stub_httpx(monkeypatch)

    wp = pytypes.ModuleType("backend.wp_client")
    wp.PEOPLE = ("tony", "kk", "nhong")
    wp.PUBLIC_BASE = "https://x.test/wp"
    wp.env = lambda: ENV
    wp.configured = lambda e: all(
        e.get(k) for k in ("WP_SITE_URL", "WP_APP_USER",
                           "WP_APP_PASSWORD"))
    wp.media_local_path = lambda u: None
    wp.upload_media = _AsyncRecorder((11, "https://x/img.jpg"))
    wp.create_post = _AsyncRecorder({"ok": True, "id": 501,
                                     "link": "https://x/?p=501"})
    wp.api = _AsyncRecorder()
    wp.paragraphs = lambda t: "".join(
        f"<p>{ln}</p>\n" for ln in t.split("\n") if ln.strip())
    wp.https = lambda u: u

    backend = sys.modules.get("backend") or pytypes.ModuleType("backend")
    backend.__path__ = []
    backend.wp_client = wp
    monkeypatch.setitem(sys.modules, "backend", backend)
    monkeypatch.setitem(sys.modules, "backend.wp_client", wp)

    spec = importlib.util.spec_from_file_location(
        f"tools_d.cpt_post_chaba_{id(wp)}", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, wp


def _runner(instance="kk", identity=None):
    r = SimpleNamespace(instance=instance)
    r._memory_identity = lambda: identity
    return r


# ------------------------------------------------------------ pure helpers

def test_title_standard(monkeypatch):
    mod, _ = _load_tool(monkeypatch)
    assert mod._title("expense", "",
                      {"vendor": "7-Eleven",
                       "receipt_date": "2026-10-15"}) == \
        "Expense — 7-Eleven 2026-10-15"
    assert mod._title("contact", "Somsak", {}) == "Contact — Somsak"
    assert mod._title("reminder", "pay AIS", {}) == "Reminder — pay AIS"
    assert mod._title("asset", "CR-V", {}) == "Asset — CR-V"


def test_slug_thai_hash_stable(monkeypatch):
    mod, _ = _load_tool(monkeypatch)
    a = mod._slug("contact", "ช่างสมศักดิ์")
    assert a == mod._slug("contact", "ช่างสมศักดิ์")
    assert a.startswith("contact-")


def test_person_default_chain(monkeypatch):
    mod, _ = _load_tool(monkeypatch)
    assert mod._person(_runner("kk"), "") == "kk"          # boss of kk-hom
    assert mod._person(_runner("kk-dev"), "") == "kk"
    assert mod._person(_runner("dev", "person.nhong"), "") == "nhong"
    assert mod._person(_runner("kk"), "nhong") == "nhong"  # explicit
    assert mod._person(_runner("dev", "nobody"), "") == ""


def test_meta_scoped_to_kind(monkeypatch):
    mod, _ = _load_tool(monkeypatch)
    meta, dropped = mod._collect_meta(
        "expense", "kk", {"amount": "320", "vendor": "PTT",
                          "phone": "081"})
    assert meta == {"amount": "320", "vendor": "PTT", "saved_by": "kk"}
    assert dropped == ["phone"]


# ------------------------------------------------------------------- run()

def _run(mod, runner, **args):
    return asyncio.run(mod.run(runner, **args))


def test_guards(monkeypatch):
    mod, _ = _load_tool(monkeypatch)
    res = _run(mod, _runner(), kind="post", title="x")
    assert res["ok"] is False and "wp_post" in res["error"]
    res = _run(mod, _runner(), kind="contact")
    assert res["ok"] is False and "title" in res["error"]
    res = _run(mod, _runner(), kind="expense", status="bogus")
    assert res["ok"] is False and "status" in res["error"]


def test_expense_creates_with_meta_and_slug(monkeypatch):
    mod, wp = _load_tool(monkeypatch)
    res = _run(mod, _runner("kk"), kind="expense", vendor="PTT",
               amount="320", receipt_date="2026-10-15")
    assert res["ok"] and res["id"] == 501
    _a, kw = wp.create_post.calls[0]
    assert kw["post_type"] == "expense"
    assert kw["meta"]["currency"] == "THB"
    assert kw["meta"]["saved_by"] == "kk"
    assert kw["slug"].startswith("expense-")
    assert res["title"] == "Expense — PTT 2026-10-15"


def test_meta_skew_retry_drops_saved_by_first(monkeypatch):
    """chaba-boards <0.5.1 rejects saved_by — the retry drops only
    saved_by, keeping the keys that have been registered since 0.3.x."""
    mod, wp = _load_tool(monkeypatch)
    calls = []

    async def flaky(client, env, title, body, **kw):
        calls.append(kw)
        if "saved_by" in (kw.get("meta") or {}):
            return {"ok": False,
                    "error": "post create failed 400: rest_invalid_meta"}
        return {"ok": True, "id": 77, "link": "https://x/?p=77"}

    wp.create_post = flaky
    res = _run(mod, _runner(), kind="expense", vendor="PTT", amount="10")
    assert res["ok"]
    assert res["meta_written"] == ["amount", "currency", "vendor"]
    assert len(calls) == 2 and "saved_by" not in calls[1]["meta"]
    assert "<0.5.1" in (res["note"] or "")


def test_contact_upserts_by_slug(monkeypatch):
    mod, wp = _load_tool(monkeypatch)

    class Resp:
        def __init__(self, payload, code=200):
            self._p, self.status_code, self.text = payload, code, ""

        def json(self):
            return self._p

    posts = []

    async def api(client, env, method, route, **kw):
        if method == "GET":
            return Resp([{"id": 42}])
        posts.append((route, kw))
        return Resp({"id": 42, "link": "https://x/contact/honda"})

    wp.api = api
    res = _run(mod, _runner("kk"), kind="contact",
               title="Honda Service", phone="02123456")
    assert res["ok"] and res["updated"] and res["id"] == 42
    route, kw = posts[0]
    assert route == "contact/42"
    assert kw["json"]["meta"]["phone"] == "02123456"


def test_expense_never_upserts(monkeypatch):
    mod, wp = _load_tool(monkeypatch)

    async def no_get(client, env, method, route, **kw):
        raise AssertionError("slug lookup ran for an event kind")

    wp.api = no_get
    res = _run(mod, _runner(), kind="expense", vendor="7-Eleven",
               amount="45")
    assert res["ok"] and res["created"]


def test_manifest_and_declare_names_match(monkeypatch):
    """manifest key == DECLARATION name (tools_loader._validate)."""
    mod, _ = _load_tool(monkeypatch)
    frag = yaml.safe_load(
        (DROP / "backend" / "tools.d" / "manifest.cpt_post.yml")
        .read_text())
    cfg = frag["tools"]["cpt_post"]
    assert cfg["module"] == "cpt_post"
    assert mod.DECLARATION["name"] == "cpt_post"
    assert mod.DECLARATION["parameters"]["required"] == ["kind"]


# ------------------------------------------------------------- patch gate

@pytest.mark.skipif(not (ADA_PI / ".git").exists(),
                    reason="no ada-voice checkout reachable")
def test_patches_apply_clean(tmp_path):
    """Base-commit guard: every patch must apply OR already be merged
    upstream; divergence only fails when nothing in the drop landed
    (pending drop on a rotted base — tests/ada/_drops.py)."""
    dst = tmp_path / "ada-voice"
    subprocess.run(["git", "clone", "-q", "--depth", "1",
                    ADA_PI.as_uri(), str(dst)],
                   check=True, timeout=120)
    states = {rel: check_patch(DROP / rel, dst) for rel in PATCHES}
    assert drop_guard_ok(states.values()), (
        f"drop rotted on its base — re-dispatch: {states}")
    # the new tool file itself must compile — merged upstream = already
    # in the clone; still pending = copy the staged file in.
    tgt = dst / "backend" / "tools.d" / "cpt_post.py"
    if not tgt.exists():
        subprocess.run(["cp", str(TOOL), str(tgt)], check=True)
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(tgt)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]
