"""Unit tests for the tg-forward-provenance drop staged under
integrations/ada-voice/ (card tg-forward-provenance, 2026-10-17).

The incident (2026-10-16): Tony forwarded 3 of Michael's voice clips to
@KrautMNBot's DM. The relay filed them under corpus/tg/tony/ and the
transcript turns went to Kraut as caller=tony, so the persona answered
as if Tony had spoken them — manual refile fixed the corpus.

Most of the fix already shipped in ada-voice `b205457` ("mn-ha relay
batch" — _forward_label reads forward_origin, clips file under the
original sender, forwarded_by lands in the manifest, every handled turn
type gets an attribution prefix). THIS drop closes the remaining spec
gaps on top of it:

- hidden/unknown origin: the label now notes 'origin hidden' and falls
  back to the FORWARDER's identity when Telegram gives no name
  (hidden_user with an empty sender_user_name, legacy
  forward_sender_name absent) — previously the label was a bare
  'hidden user' and nothing marked the forward as obscured;
- forwarded media with no dedicated renderer (document, video,
  animation, sticker, contact, location, venue, poll, dice) used to
  drop silently before the text check — it now reaches the persona as
  a described turn carrying the same '(forwarded from X)' prefix plus
  the sender's caption. Non-forwarded media of those kinds still drop:
  relaying every stray sticker would bill a turn for nothing.

Chaba-side coverage: the patch resolves against a live ada-voice
checkout (ADA_PI env or ~/CascadeProjects/ada-voice) via the _drops
tri-state, the patched file compiles, and the patched tg_relay is
driven standalone for _forward_label cases, corpus filing provenance,
and the handle() turn text for forwarded text/document/hidden origins.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from tests.ada._drops import apply_patch, check_patch, drop_guard_ok

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
ADA_PI = Path(os.environ.get(
    "ADA_PI", str(Path.home() / "CascadeProjects/ada-voice")))

PATCHES = [DROP / "backend/tg_relay.forward-provenance.patch"]

NEEDS_ADA_PI = pytest.mark.skipif(
    not (ADA_PI / "backend/tg_relay.py").is_file(),
    reason="no ada-voice checkout to apply the patch against")


@NEEDS_ADA_PI
class TestPatchApplies:
    def test_patch_applies_or_landed(self, tmp_path):
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend/tg_relay.py").write_bytes(
            (ADA_PI / "backend/tg_relay.py").read_bytes())
        state = check_patch(PATCHES[0], tmp_path)
        assert drop_guard_ok([state]), (
            f"drop rotted on its base — re-dispatch: {state}")

    def test_applied_file_compiles(self, tmp_path):
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend/tg_relay.py").write_bytes(
            (ADA_PI / "backend/tg_relay.py").read_bytes())
        apply_patch(PATCHES[0], tmp_path)
        f = tmp_path / "backend/tg_relay.py"
        compile(f.read_text(), str(f), "exec")


def _load(tmp_path: Path, monkeypatch):
    """Copy tg_relay.py, apply the drop, import it standalone with the
    relay env pointed at the tmp dir."""
    pytest.importorskip("httpx")
    pytest.importorskip("websockets")
    (tmp_path / "backend").mkdir(exist_ok=True)
    target = tmp_path / "backend/tg_relay.py"
    target.write_bytes((ADA_PI / "backend/tg_relay.py").read_bytes())
    apply_patch(PATCHES[0], tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADA_API_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "555")
    monkeypatch.setenv("TELEGRAM_USER_CALLERS",
                       "42:user-michael,7:user-tony")
    monkeypatch.setenv("TELEGRAM_STATE_FILE",
                       str(tmp_path / "state.json"))
    monkeypatch.setenv("TG_VOICE_CORPUS_DIR", str(tmp_path / "corpus"))
    # upstream tg_relay gained a `trivial_gate` sibling import after this
    # harness was written — stub it; the provenance paths under test
    # never reach the gate (voice turns only).
    gate_stub = types.ModuleType("trivial_gate")
    gate_stub.quiet_s = lambda: 0.0

    async def _no_gate(*_a, **_k):
        return None

    gate_stub.check = _no_gate
    monkeypatch.setitem(sys.modules, "trivial_gate", gate_stub)
    spec = importlib.util.spec_from_file_location(
        "tg_relay_patched", target)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _relay(mod, monkeypatch):
    """A TgRelay with Telegram + the persona session stubbed out."""
    relay = mod.TgRelay()
    calls = []

    async def tg(method, **kw):
        calls.append((method, kw))
        return {}

    relay.tg = tg
    relay._test_calls = calls

    class _FakeSession:
        def __init__(self, chat_id, relay_, caller=None):
            self.chat_id = chat_id
            self.caller = caller
            self.turns = []

        async def send_turn(self, text):
            self.turns.append(text)
            return ("ok", [])

        async def send_image_turn(self, img, mime, caption):
            self.turns.append(caption)
            return ("ok", [])

        async def close(self):
            pass

    monkeypatch.setattr(mod, "ChatSession", _FakeSession)
    return relay, calls


def _msg(**kw):
    m = {"message_id": 1, "date": 1760700000,
         "chat": {"id": 555, "type": "private"},
         "from": {"id": 7, "first_name": "Tony",
                  "username": "tonezzz"}}
    m.update(kw)
    return {"message": m}


@NEEDS_ADA_PI
class TestForwardLabel:
    def test_sender_user_maps_to_caller(self, tmp_path, monkeypatch):
        mod = _load(tmp_path, monkeypatch)
        label, mapped = mod._forward_label(_msg(
            forward_origin={"type": "sender_user",
                            "sender_user": {"id": 42,
                                            "first_name": "Michael"}}
        )["message"])
        assert (label, mapped) == ("user-michael", "user-michael")

    def test_sender_user_unmapped_uses_name(self, tmp_path, monkeypatch):
        mod = _load(tmp_path, monkeypatch)
        label, mapped = mod._forward_label(_msg(
            forward_origin={"type": "sender_user",
                            "sender_user": {"id": 999,
                                            "first_name": "Nong"}}
        )["message"])
        assert (label, mapped) == ("Nong", None)

    def test_hidden_user_named(self, tmp_path, monkeypatch):
        mod = _load(tmp_path, monkeypatch)
        label, mapped = mod._forward_label(_msg(
            forward_origin={"type": "hidden_user",
                            "sender_user_name": "Michael N."}
        )["message"])
        assert mapped is None
        assert label == "Michael N. — origin hidden"

    def test_hidden_user_nameless_falls_back_to_forwarder(
            self, tmp_path, monkeypatch):
        """Spec: unknown origin falls back to the FORWARDER's identity
        (Tony, id 7 -> user-tony) and is flagged hidden."""
        mod = _load(tmp_path, monkeypatch)
        label, mapped = mod._forward_label(_msg(
            forward_origin={"type": "hidden_user",
                            "sender_user_name": ""}
        )["message"])
        assert mapped is None
        assert label == "user-tony — origin hidden"

    def test_chat_and_channel_origins(self, tmp_path, monkeypatch):
        mod = _load(tmp_path, monkeypatch)
        label, mapped = mod._forward_label(_msg(
            forward_origin={"type": "chat",
                            "sender_chat": {"title": "MN House"}}
        )["message"])
        assert (label, mapped) == ("MN House", None)
        label, mapped = mod._forward_label(_msg(
            forward_origin={"type": "channel",
                            "chat": {"title": "Thai News"}}
        )["message"])
        assert (label, mapped) == ("Thai News", None)

    def test_legacy_fields(self, tmp_path, monkeypatch):
        mod = _load(tmp_path, monkeypatch)
        label, mapped = mod._forward_label(_msg(
            forward_from={"id": 42, "first_name": "Michael"})["message"])
        assert (label, mapped) == ("user-michael", "user-michael")
        label, mapped = mod._forward_label(_msg(
            forward_sender_name="Some Hidden")["message"])
        assert mapped is None
        assert label == "Some Hidden — origin hidden"
        label, mapped = mod._forward_label(_msg(
            forward_from_chat={"title": "Old Group"})["message"])
        assert (label, mapped) == ("Old Group", None)

    def test_not_a_forward(self, tmp_path, monkeypatch):
        mod = _load(tmp_path, monkeypatch)
        assert mod._forward_label(_msg(text="hi")["message"]) == (
            "", None)


@NEEDS_ADA_PI
class TestHandleTurns:
    def _turns(self, relay):
        return [t for s in relay.sessions.values() for t in s.turns]

    def test_forwarded_text_prefix(self, tmp_path, monkeypatch):
        mod = _load(tmp_path, monkeypatch)
        relay, _ = _relay(mod, monkeypatch)
        asyncio.run(relay.handle(_msg(
            text="tell kraut hi",
            forward_origin={"type": "sender_user",
                            "sender_user": {"id": 42,
                                            "first_name": "Michael"}})))
        assert self._turns(relay) == [
            "(forwarded from user-michael): tell kraut hi"]

    def test_hidden_origin_text_flagged(self, tmp_path, monkeypatch):
        mod = _load(tmp_path, monkeypatch)
        relay, _ = _relay(mod, monkeypatch)
        asyncio.run(relay.handle(_msg(
            text="mystery words",
            forward_origin={"type": "hidden_user",
                            "sender_user_name": "Unknown Dude"})))
        assert self._turns(relay) == [
            "(forwarded from Unknown Dude — origin hidden): "
            "mystery words"]

    def test_forwarded_document_described(self, tmp_path, monkeypatch):
        """Spec case (3): a forwarded document reaches the persona as a
        described turn with the same attribution prefix + caption."""
        mod = _load(tmp_path, monkeypatch)
        relay, _ = _relay(mod, monkeypatch)
        asyncio.run(relay.handle(_msg(
            document={"file_id": "doc1", "file_name": "quartal.pdf",
                      "mime_type": "application/pdf",
                      "file_size": 204800},
            caption="michael's report",
            forward_origin={"type": "sender_user",
                            "sender_user": {"id": 42,
                                            "first_name": "Michael"}})))
        assert self._turns(relay) == [
            "(forwarded from user-michael) [received a document: "
            "quartal.pdf (200 KB) — content not viewable here] "
            "Their caption: michael's report"]

    def test_forwarded_sticker_described(self, tmp_path, monkeypatch):
        mod = _load(tmp_path, monkeypatch)
        relay, _ = _relay(mod, monkeypatch)
        asyncio.run(relay.handle(_msg(
            sticker={"file_id": "st1", "emoji": "\U0001f601"},
            forward_origin={"type": "hidden_user",
                            "sender_user_name": "Hider"})))
        assert self._turns(relay) == [
            "(forwarded from Hider — origin hidden) [received a "
            "sticker: \U0001f601 — content not viewable here]"]

    def test_plain_document_still_dropped(self, tmp_path, monkeypatch):
        """Out of scope: non-forwarded unhandled media keeps the old
        silent-drop (relay-relaying every stray sticker bills turns)."""
        mod = _load(tmp_path, monkeypatch)
        relay, _ = _relay(mod, monkeypatch)
        asyncio.run(relay.handle(_msg(
            document={"file_id": "doc1", "file_name": "a.pdf"})))
        assert self._turns(relay) == []
        methods = [c[0] for c in relay_calls(relay)]
        assert "sendMessage" not in methods

    def test_forwarded_voice_files_under_origin(
            self, tmp_path, monkeypatch):
        """The 2026-10-16 incident: Tony forwards Michael's clip — the
        file must land under corpus/user-michael/ with forwarded_by
        provenance, not under the forwarder's dir."""
        mod = _load(tmp_path, monkeypatch)
        relay, _ = _relay(mod, monkeypatch)
        msg = _msg(
            voice={"file_id": "v1", "duration": 3,
                   "mime_type": "audio/ogg"},
            forward_origin={"type": "sender_user",
                            "sender_user": {"id": 42,
                                            "first_name": "Michael"}}
        )["message"]

        async def _dl(file_id):
            return b"\x00" * 64, "voice/file_1.oga"

        relay._download_file = _dl
        dest, _dur = asyncio.run(relay._save_voice_clip(
            msg, msg["voice"], "voice", 555, 7, None,
            mod._forward_label(msg)))
        corpus = Path(mod.VOICE_CORPUS_DIR)
        assert dest.parent == corpus / "user-michael"
        assert dest.is_file()
        manifest = (corpus / "manifest.jsonl").read_text().strip()
        entry = json.loads(manifest.splitlines()[-1])
        assert entry["sender"] == "user-michael"
        assert entry["forward_from"] == "user-michael"
        assert entry["forwarded_by"] == "user-tony"

    def test_hidden_voice_files_under_forwarder(
            self, tmp_path, monkeypatch):
        """Hidden origin can't be verified — the clip files under the
        forwarder but the manifest records it as hidden."""
        mod = _load(tmp_path, monkeypatch)
        relay, _ = _relay(mod, monkeypatch)
        msg = _msg(
            voice={"file_id": "v2", "duration": 2,
                   "mime_type": "audio/ogg"},
            forward_origin={"type": "hidden_user",
                            "sender_user_name": "Claimed Name"}
        )["message"]

        async def _dl(file_id):
            return b"\x01" * 64, "voice/file_2.oga"

        relay._download_file = _dl
        dest, _dur = asyncio.run(relay._save_voice_clip(
            msg, msg["voice"], "voice", 555, 7, None,
            mod._forward_label(msg)))
        corpus = Path(mod.VOICE_CORPUS_DIR)
        assert dest.parent == corpus / "user-tony"
        entry = json.loads(
            (corpus / "manifest.jsonl").read_text().splitlines()[-1])
        assert entry["forward_from"] == "Claimed Name — origin hidden"
        assert entry["forwarded_by"] == "user-tony"


def relay_calls(relay):
    """sendMessage calls captured via the tg stub — the relay's own
    tg() was replaced, so calls live on the bound closure: recover via
    the sessions test's own stub list. Falls back to []."""
    return getattr(relay, "_test_calls", [])
