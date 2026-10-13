"""Unit tests for the line reply-routing drop staged under
integrations/ada-pi/ (card line-tool-reply-routing-answers-leave-th-5c73e7,
ADA-0606, 2026-10-13).

The card: a bare chat_send ("reply in this room") left the originating
chat — answers landed in the lane default room or the owner's DM. Two
mechanism breaks in backend/line_relay.py:

1. _recent_chat was keyed by persona name ('ada') while /send looks it
   up by ADA_INSTANCE_ID ('tony') — the join never matched.
2. _recent_chat was written only inside _deliver_turn (voice-transcript
   turns) — text/image/file turns never recorded their chat at all.

The drop adds three layers, each independently safe:

- ?origin_chat=<chatId> on the relay's ws connect pins the session's
  chat; pwa_server stashes it per session_id and chat_send puts it in
  the /send payload's chat_id — exact binding.
- Backends announce ADA_INSTANCE_ID in the ws 'ready' hello; the relay
  learns persona->instance and keys _recent_chat under both names
  (LINE_PERSONA_INSTANCE env remains the configured fallback).
- _note_recent() runs on every delivered-turn path, not just voice.

Same harness as test_line_image_delivery: the unified diffs are applied
to a copy of the ada-pi source (ADA_PI env or ~/CascadeProjects/ada-pi),
compiled, and exercised with stubbed http/ws/web — including an
end-to-end /send through the real route handler. Skips when no ada-pi
checkout is reachable.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import types as pytypes
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-pi"
PATCHES = {
    "backend/line_relay.py":
        DROP / "backend" / "line_relay.reply-routing.patch",
    "backend/tool_runner/__init__.py":
        DROP / "backend" / "tool_runner.reply-routing.patch",
    "backend/tool_runner/chat.py":
        DROP / "backend" / "tool_runner.reply-routing.patch",
    "pwa_server.py":
        DROP / "backend" / "pwa_server.reply-routing.patch",
}
ADA_PI = Path(os.environ.get("ADA_PI",
                             str(Path.home() / "CascadeProjects/ada-pi")))


def _ada_pi_file(rel: str) -> Path:
    p = ADA_PI / rel
    if not p.exists():
        pytest.skip(f"no ada-pi checkout at {ADA_PI} — drop ships the "
                    f"patches, not the files")
    return p


@pytest.fixture()
def patched_tree(tmp_path):
    """Apply the drop patches to copies of the ada-pi sources."""
    for rel, patch in PATCHES.items():
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(_ada_pi_file(rel).read_bytes())
    subprocess.run(
        ["git", "apply"] +
        [str(p) for p in dict.fromkeys(PATCHES.values())],
        cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_patches_apply_and_compile(patched_tree):
    for rel in PATCHES:
        compile((patched_tree / rel).read_text(),
                str(patched_tree / rel), "exec")


@pytest.fixture()
def relay_mod(patched_tree, monkeypatch):
    """Import the patched line_relay with web deps stubbed."""
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
    monkeypatch.setenv("LINE_MEDIA_ARCHIVE_DIR", "/tmp/x-arch")
    monkeypatch.setenv("LINE_IMG_CACHE_DIR", "/tmp/x-img")
    spec = importlib.util.spec_from_file_location(
        "line_relay_patched", patched_tree / "backend" / "line_relay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _relay(mod, http=None):
    relay = mod.LineRelay.__new__(mod.LineRelay)
    relay.http = http or _Http()
    relay.sessions = {}
    relay._imgs = {}
    relay._names = {}
    relay._refused = {}
    relay._room_pin = {}
    relay._recent_chat = {}
    relay._ws_instance = {}
    return relay


class _Resp:
    def __init__(self, content=b"", status=200, payload=None):
        self.content = content
        self.headers = {"content-type": "image/jpeg"}
        self.status_code = status
        self._payload = payload or {"ok": True}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _Http:
    def __init__(self):
        self.posts, self.gets = [], []

    async def post(self, url, json=None, headers=None, **kw):
        self.posts.append((url, json, headers or {}))
        return _Resp()

    async def get(self, url, **kw):
        self.gets.append(url)
        return _Resp()


# ----------------------------------------------------------- env mapping


class TestPersonaInstances:
    def test_env_parse(self, relay_mod, monkeypatch):
        monkeypatch.setenv("LINE_PERSONA_INSTANCE",
                           "ada:tony,kaewta:kk, chaba:chaba")
        assert relay_mod._persona_instances() == {
            "ada": "tony", "kaewta": "kk", "chaba": "chaba"}

    def test_env_empty(self, relay_mod, monkeypatch):
        monkeypatch.delenv("LINE_PERSONA_INSTANCE", raising=False)
        assert relay_mod._persona_instances() == {}


# -------------------------------------------------------- _note_recent


class TestNoteRecent:
    def test_records_under_instance_alias(self, relay_mod, monkeypatch):
        """THE BUG: /send looks up _recent_chat[instance] but only the
        persona name was ever recorded — the join must dual-key."""
        monkeypatch.setenv("LINE_PERSONA_INSTANCE", "ada:tony")
        relay = _relay(relay_mod)
        relay._note_recent("ada", "C_room42")
        assert relay._recent_chat["ada"][0] == "C_room42"
        assert relay._recent_chat["tony"][0] == "C_room42"

    def test_persona_only_when_unmapped(self, relay_mod, monkeypatch):
        monkeypatch.delenv("LINE_PERSONA_INSTANCE", raising=False)
        relay = _relay(relay_mod)
        relay._note_recent("ada", "U_dm")
        assert "ada" in relay._recent_chat
        assert len(relay._recent_chat) == 1


# ------------------------------------------------------ instance learn


class TestInstanceLearn:
    def test_ready_hello_wins_over_env(self, relay_mod, monkeypatch):
        """Backend self-report beats configured env (stale config is a
        real failure mode); env is the pre-connect fallback."""
        monkeypatch.setenv("LINE_PERSONA_INSTANCE", "ada:oldtony")
        relay = _relay(relay_mod)
        # 'ada' defaults to ADA_WS_URL when unlisted in LINE_NAME_BACKENDS
        relay._learn_instance(relay_mod.ADA_WS_URL, " tony ")
        assert relay._persona_instance("ada") == "tony"
        relay._note_recent("ada", "C_room")
        assert relay._recent_chat["tony"][0] == "C_room"

    def test_env_fallback_when_not_announced(self, relay_mod,
                                             monkeypatch):
        monkeypatch.setenv("LINE_PERSONA_INSTANCE", "kaewta:kk")
        relay = _relay(relay_mod)
        assert relay._persona_instance("kaewta") == "kk"

    def test_blank_announce_ignored(self, relay_mod):
        relay = _relay(relay_mod)
        relay._learn_instance("ws://x:1/ws", "   ")
        assert relay._ws_instance == {}


# -------------------------------------------------- ws reader learning


class _WS:
    """Async-iterable fake websocket yielding canned frames then idle."""

    def __init__(self, frames):
        self._it = iter(frames)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            await asyncio.sleep(3600)


class TestReadyLearning:
    def test_reader_learns_instance(self, relay_mod, monkeypatch):
        relay = _relay(relay_mod)
        sess = relay_mod.ChatSession(
            "U1", relay, ws_url=relay_mod.ADA_WS_URL, chat_id="C_room")
        frame = json.dumps({"type": "ready", "session": "abc",
                            "instance": "tony"})

        async def run():
            sess.ws = _WS([frame])
            task = asyncio.create_task(sess._reader())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run())
        assert relay._ws_instance[relay_mod.ADA_WS_URL] == "tony"
        assert sess._current.get_nowait()["type"] == "ready"


# --------------------------------------------------- origin_chat pin


class TestOriginChatPin:
    def test_connect_url_carries_origin(self, relay_mod, monkeypatch):
        captured = {}

        async def fake_connect(url, **kw):
            captured["url"] = url
            return _WS([])

        monkeypatch.setattr(relay_mod.websockets, "connect",
                            fake_connect)
        relay = _relay(relay_mod)
        sess = relay_mod.ChatSession(
            "U1", relay, ws_url="ws://127.0.0.1:8007/ws",
            caller=None, chat_id="C_room99")
        asyncio.run(sess.ensure())
        assert "&origin_chat=C_room99" in captured["url"]
        assert "&channel=line" in captured["url"]

    def test_no_origin_when_unbound(self, relay_mod, monkeypatch):
        captured = {}

        async def fake_connect(url, **kw):
            captured["url"] = url
            return _WS([])

        monkeypatch.setattr(relay_mod.websockets, "connect",
                            fake_connect)
        relay = _relay(relay_mod)
        sess = relay_mod.ChatSession("U1", relay, ws_url="ws://x/ws")
        asyncio.run(sess.ensure())
        assert "origin_chat" not in captured["url"]

    def test_session_factory_binds_chat(self, relay_mod):
        relay = _relay(relay_mod)
        sess = relay._session(("C_a", "U1", "ada"), "U1",
                              "ws://a/ws", None, chat_id="C_a")
        assert sess.chat_id == "C_a"
        # A session keyed under a different chat must not reuse a stale
        # binding.
        sess2 = relay._session(("C_a", "U1", "ada"), "U1",
                               "ws://a/ws", None, chat_id="C_b")
        assert sess2.chat_id == "C_b"


# ------------------------------------------------------ /send routing


class TestSendRouting:
    """End-to-end through the real /send route handler — Starlette and
    uvicorn stubbed so _webhook_server wires routes without serving."""

    def _send_handler(self, mod, relay, monkeypatch):
        st_app = pytypes.ModuleType("starlette.applications")
        st_req = pytypes.ModuleType("starlette.requests")
        st_res = pytypes.ModuleType("starlette.responses")
        st_rout = pytypes.ModuleType("starlette.routing")
        st_root = pytypes.ModuleType("starlette")
        uvicorn = pytypes.ModuleType("uvicorn")

        class _Starlette:
            def __init__(self, routes=None, **kw):
                self.routes = routes

        class _Route:
            def __init__(self, path, endpoint, methods=None):
                self.path = path
                st_rout.captured[path] = endpoint

        class _JSONResponse:
            def __init__(self, data, status_code=200):
                self.data, self.status_code = data, status_code

        class _Cfg:
            def __init__(self, *a, **k):
                pass

        class _Server:
            def __init__(self, *a, **k):
                pass

            async def serve(self):
                return

        st_rout.captured = {}
        st_app.Starlette = _Starlette
        st_req.Request = object
        st_res.JSONResponse = _JSONResponse
        st_res.Response = object
        st_rout.Route = _Route
        uvicorn.Config = _Cfg
        uvicorn.Server = _Server
        for name, m in (("starlette", st_root),
                        ("starlette.applications", st_app),
                        ("starlette.requests", st_req),
                        ("starlette.responses", st_res),
                        ("starlette.routing", st_rout),
                        ("uvicorn", uvicorn)):
            monkeypatch.setitem(sys.modules, name, m)
        monkeypatch.setattr(mod, "CHANNEL_SECRET", "x")
        asyncio.run(relay._webhook_server())
        return st_rout.captured["/send"]

    @staticmethod
    def _req(body):
        async def _json():
            return body
        return SimpleNamespace(json=_json)

    ROOM = "C" + "0123456789abcdef" * 2
    OTHER = "C" + "fedcba9876543210" * 2
    OWNER = "U" + "0011223344556677" * 2

    def test_bare_send_lands_in_recent_room(
            self, relay_mod, monkeypatch):
        """The card's bug verbatim: instance 'tony' answers in room
        ROOM; the queued send must land there, not a DM/default."""
        monkeypatch.setenv("LINE_PERSONA_INSTANCE", "ada:tony")
        monkeypatch.setenv("LINE_ALLOWED_USER_IDS", self.OWNER)
        http = _Http()
        relay = _relay(relay_mod, http)
        relay._note_recent("ada", self.ROOM)  # a routed turn happened
        send = self._send_handler(relay_mod, relay, monkeypatch)
        res = asyncio.run(send(self._req(
            {"text": "here", "instance": "tony"})))
        assert res.data["ok"] is True and res.data["to"] == self.ROOM
        push = [p for p in http.posts if "/push" in p[0]]
        assert push and push[-1][1]["to"] == self.ROOM

    def test_explicit_chat_id_origin_wins(
            self, relay_mod, monkeypatch):
        """The pinned ?origin_chat arrives as chat_id in the payload —
        exact binding even when another room is 'recent'."""
        monkeypatch.setenv("LINE_PERSONA_INSTANCE", "ada:tony")
        monkeypatch.setenv("LINE_ALLOWED_USER_IDS", self.OWNER)
        http = _Http()
        relay = _relay(relay_mod, http)
        relay._note_recent("ada", self.OTHER)
        send = self._send_handler(relay_mod, relay, monkeypatch)
        res = asyncio.run(send(self._req(
            {"text": "x", "chat_id": self.ROOM, "instance": "tony"})))
        assert res.data["to"] == self.ROOM

    def test_no_origin_falls_back_to_owner_dm(
            self, relay_mod, monkeypatch):
        """No recent turn, no lane default: the historical last resort
        (first allowed user) still applies — unchanged behavior."""
        monkeypatch.setenv("LINE_ALLOWED_USER_IDS", self.OWNER)
        relay = _relay(relay_mod, _Http())
        send = self._send_handler(relay_mod, relay, monkeypatch)
        res = asyncio.run(send(self._req(
            {"text": "x", "instance": "tony"})))
        assert res.data["to"] == self.OWNER

    def test_lane_allow_still_gates_origin(
            self, relay_mod, monkeypatch):
        """An origin pin can't carry a send outside the lane's
        allowlist — the hard gate runs after resolution."""
        monkeypatch.setenv("LINE_PERSONA_INSTANCE", "ada:tony")
        monkeypatch.setenv("LINE_LANE_ALLOW", f"tony:{self.ROOM}")
        relay = _relay(relay_mod, _Http())
        send = self._send_handler(relay_mod, relay, monkeypatch)
        res = asyncio.run(send(self._req(
            {"text": "x", "chat_id": self.OTHER, "instance": "tony"})))
        assert res.status_code == 403


# ----------------------------------------- tool_runner / pwa_server


class TestChatSendPayload:
    """_chat_send_run builds the /send payload — ast-extracted and
    exec'd with stubs so the patched code itself runs."""

    def _extract(self, patched_tree):
        import ast
        import textwrap
        src = patched_tree / "backend/tool_runner/chat.py"
        tree = ast.parse(src.read_text())
        node = next(
            m for c in tree.body if isinstance(c, ast.ClassDef)
            and c.name == "ChatMixin"
            for m in c.body
            if isinstance(m, ast.AsyncFunctionDef)
            and m.name == "_chat_send_run")
        seg = textwrap.dedent(
            ast.get_source_segment(src.read_text(), node))
        import contextvars
        import logging
        from typing import Any
        caller_session = contextvars.ContextVar("t", default=None)
        ns = {"os": os, "json": json, "asyncio": asyncio,
              "logger": logging.getLogger("t"),
              "_CALLER_SESSION": caller_session, "Any": Any}
        exec(compile(seg, str(src), "exec"), ns)
        return ns["_chat_send_run"], caller_session

    def _run(self, patched_tree, monkeypatch, tmp_path, *,
             to="", origin="C_room", session="s1"):
        fn, cvar = self._extract(patched_tree)
        posts = []

        class _FakeResp:
            def __init__(self, payload):
                self._p = payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(self._p).encode()

        import urllib.request
        real_urlopen = urllib.request.urlopen

        def fake_urlopen(req, timeout=0):
            posts.append((req.full_url, json.loads(req.data)))
            if "/send" in req.full_url:
                return _FakeResp({"ok": True, "to": "?"})
            return _FakeResp({})

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        runner = SimpleNamespace(
            session_id=session,
            session_origin={session: origin} if origin else {},
            mddb=None)
        cvar.set(session)
        asyncio.run(fn(runner, "job-1", "line", "hi", "", "", to, ""))
        monkeypatch.setattr(urllib.request, "urlopen", real_urlopen)
        send_posts = [p for p in posts if "/send" in p[0]]
        assert send_posts, "no relay POST captured"
        return send_posts[0][1]

    def test_origin_fills_empty_to(self, patched_tree, monkeypatch,
                                   tmp_path):
        payload = self._run(patched_tree, monkeypatch, tmp_path)
        assert payload["chat_id"] == "C_room"
        assert payload["to"] == ""

    def test_explicit_to_wins(self, patched_tree, monkeypatch,
                              tmp_path):
        payload = self._run(patched_tree, monkeypatch, tmp_path,
                            to="U_person")
        assert payload["chat_id"] == "U_person"
        assert payload["to"] == "U_person"

    def test_no_origin_stays_empty(self, patched_tree, monkeypatch,
                                   tmp_path):
        payload = self._run(patched_tree, monkeypatch, tmp_path,
                            origin="")
        assert payload["chat_id"] == ""


class TestPwaServerWiring:
    """pwa_server.py is import-heavy (FastAPI, live providers) — the
    compile gate above covers syntax; here we pin the wiring markers so
    the drop can't silently lose a half of the handshake."""

    def test_ready_carries_instance(self, patched_tree):
        text = (patched_tree / "pwa_server.py").read_text()
        assert text.count('"instance": os.environ.get(') == 2

    def test_origin_stashed_and_cleaned(self, patched_tree):
        text = (patched_tree / "pwa_server.py").read_text()
        assert 'getattr(tool_runner, "session_origin", None)' in text
        assert "_origin_map[session_id] = (" in text
        assert "_origin_map.pop(session_id" in text
        assert 'query_params.get("origin_chat")' in text


class TestRunnerInit:
    def test_session_origin_declared(self, patched_tree):
        text = (patched_tree
                / "backend/tool_runner/__init__.py").read_text()
        assert "self.session_origin: dict[str, str] = {}" in text
