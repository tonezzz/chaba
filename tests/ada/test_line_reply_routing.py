"""Unit tests for the line-tool-reply-routing drop staged under
integrations/ada-voice/ (card line-tool-reply-routing-answers-leave-th-5c73e7,
2026-10-13).

The bug: a persona's chat_send inside a LINE turn had no notion of the
originating chat — relay /send fell back to _recent_chat (written keyed
by persona name but read keyed by ADA_INSTANCE_ID — a dead map), then
LINE_LANE_DEFAULT, then the first allowed user, so answers left the
asking chat for the lane default room or the owner's DM.

The drop fixes both ends: the relay binds each backend session to its
originating chat (&chat_id= on the ws connect), the runner records it in
SESSION_CHAT and chat_send defaults `to` to it, and /send records
deliveries under the instance key so the fallback map is readable again.

Chaba-side coverage (the ada-pi-side suite is tests/test_line_reply_context.py
in the drop):

- every patch in the drop resolves against a live ada-voice checkout
  (ADA_PI env or ~/CascadeProjects/ada-voice): applies while pending, or
  already-merged/diverged -> the live file is tested (tests/ada/_drops.py
  — the drop shipped in ada-voice 8f8f488, so this guards the merged
  implementation now);
- the patched line_relay actually carries chat_id onto the ws URL and
  through _session();
- the patched tool_runner resolves session_chat_id correctly.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import types as pytypes
from pathlib import Path
from unittest import mock

import pytest

from tests.ada._drops import apply_patch, check_patch, drop_guard_ok

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
ADA_PI = Path(os.environ.get(
    "ADA_PI", str(Path.home() / "CascadeProjects/ada-voice")))

PATCHES = [
    DROP / "backend/line_relay.reply-routing.patch",
    DROP / "backend/tg_relay.reply-routing.patch",
    DROP / "backend/tool_runner.reply-routing.patch",
    DROP / "backend/test_line_relay_group.reply-routing.patch",
    DROP / "pwa_server.reply-routing.patch",
]
NEW_FILES = [DROP / "tests/test_line_reply_context.py"]

NEEDS_ADA_PI = pytest.mark.skipif(
    not (ADA_PI / "backend/line_relay.py").is_file(),
    reason="no ada-voice checkout to apply the patch against")


def _clean_checkout(tmp_path: Path) -> Path:
    """Copy ada-voice into tmp so patches apply without touching the real
    checkout — only the files the drop touches need to exist, but a
    whole-tree copy keeps relative paths honest (backend/, tests/,
    pwa_server.py at root)."""
    import shutil
    src = tmp_path / "ada-voice"
    for rel in ("backend", "tests"):
        shutil.copytree(ADA_PI / rel, src / rel,
                        ignore=shutil.ignore_patterns("__pycache__"))
    for f in ADA_PI.iterdir():
        if f.is_file():
            shutil.copy2(f, src / f.name)
    return src


@NEEDS_ADA_PI
class TestPatchApplies:
    def test_patches_apply_or_landed(self, tmp_path):
        """Tri-state per patch: applies (drop pending), merged (already
        upstream), diverged. Divergence fails only when NOTHING in the
        drop merged — a pending drop whose base rotted. Landed drops
        legitimately drift (tests/ada/_drops.py)."""
        src = _clean_checkout(tmp_path)
        states = {p.name: check_patch(p, src) for p in PATCHES}
        assert drop_guard_ok(states.values()), (
            f"drop rotted on its base — re-dispatch: {states}")

    def test_applied_files_compile(self, tmp_path):
        src = _clean_checkout(tmp_path)
        for p in PATCHES:
            apply_patch(p, src)
        for f in NEW_FILES:  # install step copies new files verbatim
            (src / "tests" / f.name).write_bytes(f.read_bytes())
        for rel in ("backend/line_relay.py", "backend/tg_relay.py",
                    "backend/tool_runner/common.py",
                    "backend/tool_runner/chat.py",
                    "pwa_server.py",
                    "tests/test_line_relay_group.py",
                    "tests/test_line_reply_context.py"):
            f = src / rel
            compile(f.read_text(), str(f), "exec")

    def test_new_test_file_ships_and_compiles(self):
        for f in NEW_FILES:
            assert f.is_file(), f
            compile(f.read_text(), str(f), "exec")


@NEEDS_ADA_PI
class TestPatchedRelay:
    """Drive the patched line_relay standalone (httpx/websockets must be
    importable — they are wherever this test matters)."""

    def _load(self, tmp_path, monkeypatch):
        pytest.importorskip("httpx")
        pytest.importorskip("websockets")
        import importlib.util
        src = tmp_path / "backend"
        src.mkdir(exist_ok=True)
        target = src / "line_relay.py"
        target.write_bytes(
            (ADA_PI / "backend/line_relay.py").read_bytes())
        apply_patch(DROP / "backend/line_relay.reply-routing.patch",
                    tmp_path)
        monkeypatch.setenv("LINE_NAME_BACKENDS", "ada:ws://lane")
        spec = importlib.util.spec_from_file_location(
            "line_relay_patched", target)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_session_url_binds_originating_chat(self, tmp_path,
                                              monkeypatch):
        mod = self._load(tmp_path, monkeypatch)
        relay = mod.LineRelay()
        sess = relay._session(("C822x", "Ukk1", "kaewta"), "Ukk1",
                              "ws://lane/ws", "user-kk", "C822x")
        assert sess.chat_id == "C822x"

        urls = []

        class _WS:
            def __aiter__(self):
                async def _g():
                    return
                    yield  # pragma: no cover
                return _g()

            async def close(self):
                pass

        async def _connect(url, **kw):
            urls.append(url)
            return _WS()

        async def _go():
            with mock.patch.object(mod.websockets, "connect", _connect):
                await sess.ensure()
            await sess.close()

        asyncio.run(_go())
        assert urls and "chat_id=C822x" in urls[0]
        assert "channel=line" in urls[0]

    def test_send_records_instance_keyed_recent_chat(self, tmp_path,
                                                     monkeypatch):
        pytest.importorskip("starlette")
        pytest.importorskip("uvicorn")
        mod = self._load(tmp_path, monkeypatch)
        monkeypatch.setenv("LINE_LANE_DEFAULT", "kk:C822x")
        monkeypatch.setenv("LINE_ALLOWED_USER_IDS", "Utony9")
        relay = mod.LineRelay()
        delivered = []

        async def _deliver(uid, msgs, reply_token=None):
            delivered.append(uid)

        relay._deliver = _deliver
        relay.http = mock.MagicMock()
        captured = {}
        import uvicorn

        class _Srv:
            def __init__(self, config):
                captured["app"] = config.app

            async def serve(self):
                return None

        monkeypatch.setattr(mod, "CHANNEL_SECRET", "x")
        with mock.patch.object(uvicorn, "Server", _Srv):
            asyncio.run(relay._webhook_server())
        from starlette.testclient import TestClient
        client = TestClient(captured["app"])
        r = client.post("/send",
                        json={"instance": "kk", "text": "hello"})
        assert r.status_code == 200
        assert delivered == ["C822x"]
        assert relay._recent_chat["kk"][0] == "C822x"

    def test_group_session_key_gets_room_chat(self, tmp_path, monkeypatch):
        mod = self._load(tmp_path, monkeypatch)
        relay = mod.LineRelay()
        sess = relay._session(("C822x", "Ukk1", "kaewta"), "Ukk1",
                              "ws://lane/ws", "user-kk", "C822x")
        assert sess.chat_id == "C822x"
        sess2 = relay._session(("C822x", "Ukk1", "kaewta"), "Ukk1",
                               "ws://lane/ws", "user-kk", "C822x")
        assert sess2 is sess  # same (room, sender, persona) reuses


@NEEDS_ADA_PI
class TestPatchedToolRunner:
    """The chat_send side: session_chat_id resolves the bound chat."""

    def test_session_chat_registry_semantics(self, tmp_path):
        """Verify against the APPLIED source text, then drive the real
        helpers when they import cleanly."""
        src = _clean_checkout(tmp_path)
        apply_patch(DROP / "backend/tool_runner.reply-routing.patch", src)
        text = (src / "backend/tool_runner/common.py").read_text()
        assert "SESSION_CHAT" in text and "session_chat_id" in text
        chat = (src / "backend/tool_runner/chat.py").read_text()
        assert "session_chat_id(" in chat and "to_eff" in chat

        # Drive the real functions in-process when the module imports —
        # the copied tree's own tests/dep_stubs fills heavy deps. Load it
        # by path: 'tests' in sys.modules is already CHABA's package.
        # dep_stubs.install() fabricates fastapi/starlette/genai into
        # sys.modules globally — remove what it added or later tests
        # (ada_memory server imports) see fakes as the real packages.
        import importlib.util
        pre_modules = set(sys.modules)
        try:
            spec = importlib.util.spec_from_file_location(
                "ada_pi_dep_stubs", src / "tests/dep_stubs.py")
            stubs = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(stubs)
            stubs.install()
        except Exception:
            pass
        try:
            backend = pytypes.ModuleType("backend")
            backend.__path__ = [str(src / "backend")]
            tr = pytypes.ModuleType("backend.tool_runner")
            tr.__path__ = [str(src / "backend/tool_runner")]
            sys.modules["backend"] = backend
            sys.modules["backend.tool_runner"] = tr
            spec = importlib.util.spec_from_file_location(
                "backend.tool_runner.common",
                src / "backend/tool_runner/common.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules["backend.tool_runner.common"] = mod
            spec.loader.exec_module(mod)
        except Exception:
            pytest.skip("common.py deps not importable on this host")
        try:
            mod.SESSION_CHAT["s1"] = {"channel": "line",
                                      "chat_id": "C822x"}
            tok = mod._CALLER_SESSION.set("s1")
            try:
                runner = pytypes.SimpleNamespace(session_id=None)
                assert mod.session_chat_id(runner, "line") == "C822x"
                assert mod.session_chat_id(runner, "telegram") == ""
            finally:
                mod._CALLER_SESSION.reset(tok)
        finally:
            for name in set(sys.modules) - pre_modules:
                sys.modules.pop(name, None)
            for name in ("backend.tool_runner.common",
                         "backend.tool_runner", "backend"):
                sys.modules.pop(name, None)
