"""Proactive persona sends + in-group member mentions (card
line-proactive-persona).

A persona can INITIATE contact — not just reply: /send accepts
intent='proactive' (gated by LINE_PROACTIVE_ALLOW + per-lane/member
debounce + a per-day cap, state write-through) and mention=<name>
(real LINE mention objects on room targets, names resolved through the
_member_uid chain: label cache -> LINE_USER_CALLERS -> person aliases
-> persisted MEMBERS_FILE -> throttled mddb registry scan). On the tool
side, chat_send's mention=/intent=/cross-chat to= args are owner-tier —
a secondary (guest) turn can't make a persona ping someone.
"""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend import line_relay


def _relay(tmp):
    line_relay.PARKED_DIR = Path(tmp) / "parked"
    line_relay.SEND_LEDGER_FILE = Path(tmp) / "send-ledger.json"
    line_relay.PROACTIVE_STATE_FILE = Path(tmp) / "proactive.json"
    line_relay.MEMBERS_FILE = Path(tmp) / "members.json"
    relay = line_relay.LineRelay()
    relay.line = AsyncMock(return_value=MagicMock(status_code=200))
    http = MagicMock()
    http.get = AsyncMock(
        return_value=MagicMock(status_code=404, content=b"x"))
    relay.http = http
    # Hermetic: prime the registry-scan cache so a name miss returns {}
    # instead of dialing a real mddb. The scan test re-arms it.
    relay._reg_lookup_at = time.monotonic()
    return relay


class MemberUidTests(unittest.IsolatedAsyncioTestCase):
    """_member_uid — the name -> userId chain /send to= and mention=
    resolve through."""

    def setUp(self):
        self._p = patch.dict(os.environ, {
            "LINE_USER_CALLERS": "Unhong1:user-nhong,Ukk2:user-kk",
            "LINE_PERSON_ALIASES": "tony=user-tonezzzz",
            "LINE_ALLOWED_USER_IDS": "Utony0",
        })
        self._p.start()
        self.addCleanup(self._p.stop)

    async def test_caller_name_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            self.assertEqual(await relay._member_uid("nhong"), "Unhong1")
            self.assertEqual(await relay._member_uid("user-kk"), "Ukk2")

    async def test_owner_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            self.assertEqual(await relay._member_uid("owner"), "Utony0")

    async def test_label_cache_and_member_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            relay._names["Ukk9"] = "Kk"
            self.assertEqual(await relay._member_uid("kk"), "Ukk9")
            # persisted dir — a member who spoke before the process came
            # up resolves without env bindings.
            relay._member_note("Unew7", "Mook")
            relay2 = _relay(tmp)
            self.assertEqual(await relay2._member_uid("mook"), "Unew7")

    async def test_registry_scan_fallback(self):
        """A name only the mddb registry knows resolves via the
        throttled scan; the scan caches for the TTL."""
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            relay._reg_lookup_at = 0  # re-arm — force the real scan path
            mddb = AsyncMock()
            mddb.search_documents.return_value = [
                {"key": "Ureg5",
                 "meta": {"display_name": ["Pim"], "caller": []}},
                {"key": "Ureg6",
                 "meta": {"display_name": [], "caller": ["user-boss"]}}]
            with patch.object(line_relay, "_registry_store",
                              return_value=mddb):
                self.assertEqual(await relay._member_uid("pim"), "Ureg5")
                self.assertEqual(await relay._member_uid("user-boss"),
                                 "Ureg6")
                # second resolution rides the cache — one scan total
                self.assertEqual(
                    mddb.search_documents.call_count, 1)
                # nothing knows the name -> ''
                relay._reg_lookup_at = 0
                self.assertEqual(await relay._member_uid("ghost"), "")

    async def test_member_note_only_real_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            relay._member_note("U1", "")
            relay._member_note("Croom1", "NotAUser")  # rooms aren't members
            relay._member_note("U2", "Real")
            self.assertEqual(relay._member_dir, {"U2": "Real"})


class MentionWrapTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self._p = patch.dict(os.environ, {
            "LINE_USER_CALLERS": "Unhong1:user-nhong,Ukk2:user-kk",
            "LINE_PERSON_ALIASES": "",
        })
        self._p.start()
        self.addCleanup(self._p.stop)

    async def test_mention_object_built(self):
        """mention=nhong on a group target prepends '@Nhong ' and
        attaches the LINE mention object with UTF-16 offsets."""
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            relay._fetch_profile_name = AsyncMock(return_value="Nhong")
            text, mentionees, uids = await relay._mention_wrap(
                "[kaewta] look at this car", ["nhong"], "Cgrp1")
            self.assertEqual(text, "@Nhong [kaewta] look at this car")
            self.assertEqual(mentionees, [{
                "index": 0, "length": 6,
                "type": "user", "userId": "Unhong1"}])
            self.assertEqual(uids, ["Unhong1"])

    async def test_mention_offsets_are_utf16(self):
        """An astral char in the first display name shifts the second
        mentionee's index — LINE counts UTF-16 code units."""
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            names = {"Unhong1": "Nhong🙂", "Ukk2": "Kk"}
            relay._fetch_profile_name = AsyncMock(
                side_effect=lambda uid, gid, kind: names[uid])
            text, mentionees, uids = await relay._mention_wrap(
                "hi", ["nhong", "kk"], "Cgrp1")
            self.assertEqual(len(mentionees), 2)
            # "@Nhong🙂" = 8 utf-16 units (emoji is a surrogate pair);
            # "@Kk" sits after it + the separating space
            self.assertEqual(mentionees[1]["index"], 9)
            self.assertEqual(mentionees[1]["length"], 3)
            self.assertTrue(text.startswith("@Nhong🙂 @Kk hi"))

    async def test_mention_unknown_member_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            relay._fetch_profile_name = AsyncMock(return_value="")
            with self.assertRaises(ValueError):
                await relay._mention_wrap("hi", ["ghost"], "Cgrp1")

    async def test_mention_display_fallbacks(self):
        """No profile endpoint (unverified OA 404s) -> _names cache ->
        member dir -> the passed name."""
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            relay._fetch_profile_name = AsyncMock(return_value="")
            relay._names["Unhong1"] = "น้อง"
            text, mentionees, _ = await relay._mention_wrap(
                "hi", ["nhong"], "Cgrp1")
            self.assertTrue(text.startswith("@น้อง "))


class ProactiveGateTests(unittest.TestCase):
    """_proactive_gate — allowlist, debounce, day cap, persistence."""

    def _gate(self, tmp, inst="kaewta", chat="Cgrp1", members=None):
        relay = _relay(tmp)
        with patch.object(line_relay, "LINE_PROACTIVE_ALLOW",
                          {"kaewta", "ada"}), \
                patch.object(line_relay, "LINE_PROACTIVE_DEBOUNCE_S",
                             600.0), \
                patch.object(line_relay, "LINE_PROACTIVE_DAY_CAP", 8):
            return relay._proactive_gate(inst, chat, members or [])

    def test_allowlist_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._gate(tmp, inst="chaba")
            self.assertIsNotNone(gate)
            status, body = gate
            self.assertEqual(status, 403)
            self.assertFalse(body["ok"])

    def test_allowlist_empty_denies_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            with patch.object(line_relay, "LINE_PROACTIVE_ALLOW",
                              frozenset()):
                status, body = relay._proactive_gate("ada", "C1", [])
            self.assertEqual(status, 403)

    def test_pass_records_state_and_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._gate(tmp)
            self.assertIsNone(gate)
            state = json.loads(
                (Path(tmp) / "proactive.json").read_text())
            self.assertIn("kaewta|Cgrp1", state["last"])
            ledger = json.loads(
                (Path(tmp) / "send-ledger.json").read_text())
            day_rows = list(ledger.values())
            self.assertEqual(day_rows[0]["proactive_msgs"], 1)

    def test_debounce_same_lane_same_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self._gate(tmp))
            # immediate second send to the same chat is debounced
            gate = self._gate(tmp)
            self.assertIsNotNone(gate)
            status, body = gate
            self.assertEqual(status, 429)
            self.assertTrue(body["debounced"])
            self.assertGreater(body["retry_in_s"], 0)
            # a different chat is not under this debounce
            self.assertIsNone(self._gate(tmp, chat="Cother"))

    def test_member_debounce(self):
        """Rotating rooms doesn't evade a per-member cooldown — a
        persona can't ping the same member twice inside the window."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                self._gate(tmp, chat="C1", members=["Unhong1"]))
            gate = self._gate(tmp, chat="C2", members=["Unhong1"])
            status, body = gate
            self.assertEqual(status, 429)
            # ...but engaging a DIFFERENT member elsewhere is fine
            self.assertIsNone(
                self._gate(tmp, chat="C2", members=["Ukk2"]))

    def test_day_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            relay = _relay(tmp)
            with patch.object(line_relay, "LINE_PROACTIVE_ALLOW",
                              {"kaewta"}), \
                    patch.object(line_relay,
                                 "LINE_PROACTIVE_DEBOUNCE_S", 0.0), \
                    patch.object(line_relay, "LINE_PROACTIVE_DAY_CAP",
                                 2):
                self.assertIsNone(relay._proactive_gate("kaewta", "C1", []))
                self.assertIsNone(relay._proactive_gate("kaewta", "C1", []))
                gate = relay._proactive_gate("kaewta", "C1", [])
                self.assertIsNotNone(gate)
                status, body = gate
                self.assertEqual(status, 429)
                self.assertIn("cap", body["error"])

    def test_state_survives_restart(self):
        """Debounce state is write-through — a fresh relay (restart)
        still sees the last proactive send."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self._gate(tmp))
            relay2 = _relay(tmp)  # new instance = restart
            with patch.object(line_relay, "LINE_PROACTIVE_ALLOW",
                              {"kaewta"}), \
                    patch.object(line_relay,
                                 "LINE_PROACTIVE_DEBOUNCE_S", 600.0):
                gate = relay2._proactive_gate("kaewta", "Cgrp1", [])
            self.assertIsNotNone(gate)
            self.assertEqual(gate[0], 429)


class ChatSendPolicyTests(unittest.IsolatedAsyncioTestCase):
    """Runner side — mention=/intent='proactive'/cross-chat to= are
    owner-tier; a secondary turn can't make a persona ping a member."""

    async def asyncSetUp(self):
        from backend.tool_runner import ToolRunner
        self.runner = ToolRunner(AsyncMock(), instance_id="test")
        self.runner._chat_send_run = AsyncMock()

    async def test_plain_send_ok_on_secondary(self):
        """A same-chat plain send keeps the old carve-out — guests can
        still ask for a message in the room they're in."""
        with patch.object(type(self.runner), "_is_secondary_turn",
                          return_value=True):
            out = await self.runner.execute(
                "chat_send", {"channel": "line", "text": "hi"})
        self.assertEqual(out["status"], "queued")

    async def test_proactive_blocked_on_secondary(self):
        with patch.object(type(self.runner), "_is_secondary_turn",
                          return_value=True):
            for args in (
                {"channel": "line", "text": "hi", "intent": "proactive"},
                {"channel": "line", "text": "hi", "mention": "nhong"},
                {"channel": "line", "text": "hi", "to": "nhong"},
            ):
                # Reset the storm breaker between denials — two
                # PermissionErrors in 120s short-circuit later calls into
                # a synthesized outage instead of raising.
                self.runner._storm_open.clear()
                with self.assertRaises(PermissionError, msg=str(args)):
                    await self.runner.execute("chat_send", args)

    async def test_same_chat_to_not_blocked(self):
        """to=<the bound chat> isn't a reach-out — a guest asking for a
        message in the room they're in stays allowed."""
        from backend.tool_runner.common import SESSION_CHAT
        SESSION_CHAT["s1"] = {"channel": "line", "chat_id": "Cgrp1"}
        self.runner.session_id = "s1"
        try:
            with patch.object(type(self.runner), "_is_secondary_turn",
                              return_value=True):
                out = await self.runner.execute(
                    "chat_send",
                    {"channel": "line", "text": "hi", "to": "Cgrp1"})
            self.assertEqual(out["status"], "queued")
        finally:
            SESSION_CHAT.pop("s1", None)

    async def test_payload_carries_mention_intent(self):
        """The relay /send POST gets mention= and intent= on line; the
        tg relay never sees them."""
        posted = []

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"ok": true, "to": "C1"}'

        def fake_urlopen(req, timeout=0):
            import json as _json
            posted.append(_json.loads(req.data.decode()))
            return _Resp()

        self.runner.mddb = AsyncMock()
        real_run = type(self.runner)._chat_send_run  # unstub asyncSetUp
        with patch("urllib.request.urlopen", fake_urlopen):
            await real_run(
                self.runner,
                "job1", channel="line,telegram", text="hi",
                image_url="", video_url="", camera="", to="C1",
                mention="nhong", intent="proactive")
        line_post = next(p for p in posted if "mention" in p)
        self.assertEqual(line_post["mention"], "nhong")
        self.assertEqual(line_post["intent"], "proactive")
        tg_post = posted[1]
        self.assertNotIn("mention", tg_post)
        self.assertNotIn("intent", tg_post)


if __name__ == "__main__":
    unittest.main()
