"""Unit tests for stacks/services/nest-io/nest-io.py — the Nest I/O
fabric: ingestion tiers, session binding/co-listen, route precedence,
response-broker adapters + fallback, lane advisory.

Everything runs against an offline Fabric (offline=True) — no network,
state in a temp dir.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "stacks/services/nest-io/nest-io.py"

spec = importlib.util.spec_from_file_location("nest_io", SCRIPT)
nio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nio)


def fabric() -> nio.Fabric:
    d = tempfile.mkdtemp(prefix="nest-io-test-")
    return nio.Fabric(state_dir=Path(d), offline=True)


def with_surfaces(f: nio.Fabric) -> nio.Fabric:
    f.register_surface({"id": "pwa-iphone", "kind": "voice",
                        "room": "living-room",
                        "caps": ["listen", "speak"], "active": True})
    f.register_surface({"id": "screen-2", "kind": "screen",
                        "room": "living-room", "label": "living-room TV",
                        "is_tv": True, "caps": ["speak", "display"],
                        "target": {"vcast_screen": 2}, "active": True})
    f.register_surface({"id": "screen-5", "kind": "screen",
                        "room": "office", "label": "desk pad",
                        "caps": ["speak", "display"],
                        "target": {"vcast_screen": 5}})
    return f


class TierTest(unittest.TestCase):
    def test_discard_filler(self):
        f = fabric()
        d = f.decide_tier("um uh ok", "s1", False, False)
        self.assertEqual(d["tier"], "discard")
        self.assertIn("filler", d["reason"])

    def test_discard_empty_and_noise(self):
        f = fabric()
        self.assertEqual(f.decide_tier("", "s1", False, False)["tier"],
                         "discard")
        self.assertEqual(f.decide_tier("loud bang", "s1", False, False,
                                       kind="noise")["tier"], "discard")

    def test_discard_dup(self):
        f = fabric()
        f.decide_tier("ada what time is it", "s1", True, False)
        d = f.decide_tier("ada what time is it", "s1", True, False)
        self.assertEqual(d["tier"], "discard")
        self.assertIn("dup", d["reason"])

    def test_hot_addressed(self):
        f = fabric()
        d = f.decide_tier("ada what time is it", "s1", True, False)
        self.assertEqual(d["tier"], "hot")

    def test_hot_continues_open_session(self):
        f = fabric()
        d = f.decide_tier("yeah tell me more about it", "s1",
                          False, True)
        self.assertEqual(d["tier"], "hot")

    def test_cold_declarative_fact(self):
        f = fabric()
        d = f.decide_tier("my gate remote is in the kitchen drawer",
                          "s1", False, False)
        self.assertEqual(d["tier"], "cold")
        self.assertTrue(d["facts"])
        self.assertEqual(d["facts"][0]["kind"], "preference")

    def test_cold_remember_beats_command(self):
        f = fabric()
        d = f.decide_tier("remember that the cleaner comes on fridays",
                          "s1", True, False)
        self.assertEqual(d["tier"], "cold")
        self.assertTrue(d["facts"])

    def test_warm_ambient_content(self):
        f = fabric()
        d = f.decide_tier(
            "so the neighbor was saying the fence on the east side "
            "needs repair next month", "s1", False, False)
        self.assertEqual(d["tier"], "warm")

    def test_discard_short_noncontent(self):
        f = fabric()
        d = f.decide_tier("huh ok then", "s1", False, False)
        self.assertIn(d["tier"], ("discard", "warm"))


class SessionRouteTest(unittest.TestCase):
    def test_room_route_to_screen(self):
        f = with_surfaces(fabric())
        r = f.ingest({"surface": "pwa-iphone",
                      "text": "ada what time is it", "user": "tony"})
        self.assertEqual(r["reply"]["route"], "room")
        self.assertEqual(r["reply"]["surface"]["id"], "screen-2")

    def test_explicit_screen_override(self):
        f = with_surfaces(fabric())
        r = f.ingest({"surface": "pwa-iphone",
                      "text": "ada answer on screen 5", "user": "tony"})
        self.assertEqual(r["reply"]["route"], "explicit")
        self.assertEqual(r["reply"]["surface"]["id"], "screen-5")

    def test_explicit_tv_picks_tv_screen(self):
        f = with_surfaces(fabric())
        r = f.ingest({"surface": "pwa-iphone",
                      "text": "ada answer on the tv", "user": "tony"})
        self.assertEqual(r["reply"]["surface"]["id"], "screen-2")

    def test_reply_here_returns_origin(self):
        f = with_surfaces(fabric())
        r = f.ingest({"surface": "pwa-iphone",
                      "text": "ada answer right here", "user": "tony"})
        self.assertEqual(r["reply"]["route"], "explicit")
        self.assertEqual(r["reply"]["surface"]["id"], "pwa-iphone")

    def test_pinned_route_sticks_for_session(self):
        f = with_surfaces(fabric())
        f.ingest({"surface": "pwa-iphone", "text": "ada answer on screen 5",
                  "user": "tony"})
        r = f.ingest({"surface": "pwa-iphone",
                      "text": "and what else is there", "user": "tony"})
        ses = f.state["sessions"][r["session_id"]]
        self.assertEqual(ses["route_override"], "screen-5")
        self.assertEqual(r["reply"]["route"], "pinned")

    def test_co_listen_does_not_steal(self):
        f = with_surfaces(fabric())
        f.register_surface({"id": "pwa-ipad", "kind": "voice",
                            "room": "living-room",
                            "caps": ["listen", "speak"], "active": True})
        r1 = f.ingest({"surface": "pwa-iphone",
                       "text": "ada what time is it", "user": "tony"})
        r2 = f.ingest({"surface": "pwa-ipad",
                       "text": "and tomorrow?", "user": "tony"})
        self.assertEqual(r1["session_id"], r2["session_id"])
        ses = f.state["sessions"][r1["session_id"]]
        self.assertIn("pwa-ipad", ses["co_listeners"])
        self.assertEqual(ses["origin_surface"], "pwa-iphone")

    def test_last_active_screen_route(self):
        f = fabric()
        f.register_surface({"id": "pwa-iphone", "kind": "voice",
                            "room": "bedroom", "caps": ["speak"]})
        f.register_surface({"id": "screen-9", "kind": "screen",
                            "room": "kitchen",
                            "target": {"vcast_screen": 9}, "active": True})
        r = f.ingest({"surface": "pwa-iphone",
                      "text": "ada say something", "user": "tony"})
        self.assertEqual(r["reply"]["route"], "last-active")
        self.assertEqual(r["reply"]["surface"]["id"], "screen-9")

    def test_no_surfaces_falls_to_origin(self):
        f = fabric()
        r = f.ingest({"surface": "pwa-iphone",
                      "text": "ada say something", "user": "tony"})
        self.assertEqual(r["reply"]["route"], "origin")


class BrokerTest(unittest.TestCase):
    def test_speak_to_vcast_screen(self):
        f = with_surfaces(fabric())
        r = f.ingest({"surface": "pwa-iphone",
                      "text": "ada answer on screen 2", "user": "tony"})
        out = f.respond({"session_id": r["session_id"],
                         "text": "It is 3:40."})
        self.assertTrue(out["ok"])
        self.assertEqual(out["deliveries"][0]["via"], "vcast")
        self.assertEqual(out["reply_text"], "It is 3:40.")

    def test_card_delivery(self):
        f = with_surfaces(fabric())
        out = f.respond({"text": "done with the thing",
                         "kind": "card", "card_id": "nest-io-fabric"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["deliveries"][0]["via"], "board-api")
        self.assertEqual(out["deliveries"][0]["target"], "nest-io-fabric")

    def test_note_delivery(self):
        f = with_surfaces(fabric())
        out = f.respond({"text": "quiet note", "kind": "note"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["deliveries"][0]["target"], "bank:general")

    def test_unknown_surface_never_loses_reply(self):
        f = with_surfaces(fabric())
        r = f.ingest({"surface": "pwa-iphone", "text": "ada hi",
                      "user": "tony"})
        ses = f.state["sessions"][r["session_id"]]
        ses["reply_surface"] = "screen-5"
        f.state["surfaces"]["screen-5"]["stale"] = True
        f._send = lambda *a, **k: {"ok": False, "via": a[0],
                                   "target": a[1], "error": "down"}
        out = f.respond({"session_id": r["session_id"], "text": "hello"})
        # screen adapter failed -> chain falls back to origin ws-reply,
        # and if even that failed the final note fallback records it.
        self.assertTrue(out["ok"])
        self.assertTrue(any(d.get("ok") for d in out["deliveries"]))

    def test_raw_screen_number(self):
        f = fabric()
        out = f.respond({"screen": 7, "text": "hello screen"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["deliveries"][0]["target"], "screen-7")


class LaneTest(unittest.TestCase):
    def test_tool_turn_goes_gemini(self):
        f = fabric()
        d = f.decide_lane("ada cast the camera to the tv", True,
                          "hot", None)
        self.assertEqual(d["lane"], "gemini-live")

    def test_low_risk_qa_goes_local(self):
        f = fabric()
        d = f.decide_lane("what is the capital of france", True,
                          "hot", None)
        self.assertEqual(d["lane"], "local")

    def test_warm_tier_goes_local(self):
        f = fabric()
        d = f.decide_lane("the neighbor mentioned a fence repair", False,
                          "warm", None)
        self.assertEqual(d["lane"], "local")

    def test_caller_pin_wins(self):
        f = fabric()
        d = f.decide_lane("ada cast the camera", True, "hot",
                          "local")
        self.assertEqual(d["lane"], "local")
        self.assertEqual(d["why"], "caller-pinned")


class PersistTest(unittest.TestCase):
    def test_state_roundtrip(self):
        d = Path(tempfile.mkdtemp(prefix="nest-io-test-"))
        f = nio.Fabric(state_dir=d, offline=True)
        f.register_surface({"id": "s1", "kind": "voice"})
        f.ingest({"surface": "s1", "text": "ada hello there"})
        f.save()
        f2 = nio.Fabric(state_dir=d, offline=True)
        self.assertIn("s1", f2.state["surfaces"])
        self.assertTrue(f2.state["sessions"])
        self.assertTrue(f2.ledger)

    def test_sweep_closes_and_summarizes(self):
        d = Path(tempfile.mkdtemp(prefix="nest-io-test-"))
        f = nio.Fabric(state_dir=d, offline=True)
        r = f.ingest({"surface": "s1",
                      "text": "the dog needs a walk every morning "
                              "before breakfast starts"})
        ses = f.state["sessions"][r["session_id"]]
        # force expiry
        ses["last_input_at"] = "2020-01-01T00:00:00+00:00"
        f.sweep()
        self.assertTrue(ses.get("closed_at"))
        self.assertIsNotNone(ses.get("warm_summary"))

    def test_cold_queue_written(self):
        d = Path(tempfile.mkdtemp(prefix="nest-io-test-"))
        f = nio.Fabric(state_dir=d, offline=True)
        f.ingest({"surface": "s1",
                  "text": "my gate remote is in the kitchen drawer"})
        lines = f.cold_queue.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["kind"], "preference")
        self.assertEqual(rec["status"], "staged")


if __name__ == "__main__":
    unittest.main()
