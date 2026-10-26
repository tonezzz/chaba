"""Unit tests for the provider-neutral publication layer
(card devnest-publication-adapter-layer / OPS-0913):
scripts/board/publication.py schema, routing, visibility, noise policy,
idempotency and outbox — plus the board-api /publish wiring proving WP
is only one adapter (a mock + JsonSink receive the same canonical
event). No network: sinks are mocked, state dirs are tmp.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["BOARD_API_COMMIT"] = "0"  # tmp dirs aren't repo files

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / "board" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pub = _load("publication.py")


class RecSink(pub.Sink):
    """Mock sink — records the canonical events it receives."""

    def __init__(self, name="mock", surface="private", kinds=None,
                 fail=False):
        super().__init__(name=name, surface=surface,
                         kinds=kinds or pub.KINDS)
        self.events = []
        self.fail = fail

    def publish(self, ev):
        if self.fail:
            raise pub.DeliveryError("mock down")
        self.events.append(dict(ev))
        return {"ref": f"mock:{ev['event_id']}"}


def ev(**kw):
    base = {"kind": "progress", "title": "t", "source": "tester"}
    base.update(kw)
    return base


class PubTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.box = pub.Outbox(self.tmp / "state")
        self.noise = pub.NoisePolicy(self.tmp / "noise.json",
                                     progress_min_s=900,
                                     alert_min_s=60,
                                     telegram_min_s=600)

    def rejects(self, fn, frag):
        try:
            fn()
        except pub.PubError as e:
            self.assertIn(frag, str(e))
            return
        raise AssertionError(f"expected PubError containing {frag!r}")


class EventSchemaTest(PubTestBase):
    def test_required_fields(self):
        self.rejects(lambda: pub.validate_event({}), "kind must be")
        self.rejects(lambda: pub.validate_event(ev(kind="nope")),
                     "kind must be")
        self.rejects(lambda: pub.validate_event(ev(title="  ")),
                     "title required")
        self.rejects(lambda: pub.validate_event(
            ev(source="")), "source required")
        self.rejects(lambda: pub.validate_event(
            ev(source="Bad Name!")), "source required")
        self.rejects(lambda: pub.validate_event(
            ev(confidence="guessed")), "confidence must be")
        self.rejects(lambda: pub.validate_event(
            ev(visibility="world")), "visibility must be")
        self.rejects(lambda: pub.validate_event(
            ev(occurred_at="yesterday-ish")), "occurred_at must be")
        self.rejects(lambda: pub.validate_event(
            ev(card="Bad..Card")), "card must match")

    def test_body_required_kinds(self):
        for k in ("lesson", "report", "news"):
            self.rejects(lambda: pub.validate_event(
                ev(kind=k, evidence=["e"])), "body required")
        # progress/milestone/alert get by on a title
        for k in ("progress", "milestone", "alert"):
            e = pub.validate_event(ev(kind=k))
            self.assertEqual(e["kind"], k)

    def test_news_evidence_and_public_gate(self):
        self.rejects(lambda: pub.validate_event(
            ev(kind="news", body="b")), "news requires")
        self.rejects(lambda: pub.validate_event(
            ev(kind="news", body="b", evidence=["http://x"],
               visibility="public")), "public news requires")
        e = pub.validate_event(
            ev(kind="news", body="b", evidence=["http://x"],
               visibility="public", confidence="verified"))
        self.assertEqual(e["visibility"], "public")
        # members news needs evidence but not verified confidence
        e = pub.validate_event(ev(kind="news", body="b",
                                  evidence=["http://x"],
                                  visibility="members"))
        self.assertEqual(e["confidence"], "observed")

    def test_defaults_private_first(self):
        e = pub.validate_event(ev())
        self.assertEqual(e["visibility"], "private")
        self.assertEqual(e["confidence"], "observed")
        self.assertTrue(e["occurred_at"])
        self.assertTrue(e["event_id"].startswith("evt-"))
        self.assertTrue(e["idempotency_key"].startswith("pub-"))

    def test_deterministic_idempotency(self):
        a = pub.validate_event(ev(title="same"))
        b = pub.validate_event(ev(title="same"))
        self.assertEqual(a["idempotency_key"], b["idempotency_key"])
        self.assertEqual(a["event_id"], b["event_id"])
        c = pub.validate_event(
            ev(title="same", idempotency_key="my-key", event_id="evt-1"))
        self.assertEqual(c["idempotency_key"], "my-key")
        self.assertEqual(c["event_id"], "evt-1")

    def test_refs_and_lists(self):
        e = pub.validate_event(ev(
            project="devnest", job="job-1", card="card-1",
            parent="job-0", evidence=["a", "b"], media=["m.png"],
            audience=["tony"], meta={"x": 1}))
        self.assertEqual(e["project"], "devnest")
        self.assertEqual(e["job"], "job-1")
        self.assertEqual(e["card"], "card-1")
        self.assertEqual(e["parent"], "job-0")
        self.assertEqual(e["evidence"], ["a", "b"])
        self.assertEqual(e["media"], ["m.png"])
        self.rejects(lambda: pub.validate_event(
            ev(sinks=[])), "sinks must be a non-empty list")


class RoutingTest(PubTestBase):
    def test_default_routes(self):
        self.assertEqual(pub.DEFAULT_ROUTES["progress"],
                         ["job", "board"])
        # progress never defaults to telegram/news — no heartbeats
        for k, route in pub.DEFAULT_ROUTES.items():
            if k == "progress":
                self.assertNotIn("telegram", route)
                self.assertNotIn("news", route)
        self.assertIn("telegram", pub.DEFAULT_ROUTES["alert"])
        self.assertIn("news", pub.DEFAULT_ROUTES["news"])

    def test_explicit_sinks_and_unknown(self):
        sinks = {"a": RecSink("a"), "b": RecSink("b")}
        res = pub.publish_event(
            ev(sinks=["a"]), sinks, self.box, self.noise, "t")
        self.assertEqual(list(res["receipts"]), ["a"])
        self.assertEqual(len(sinks["a"].events), 1)
        self.assertEqual(len(sinks["b"].events), 0)
        self.rejects(lambda: pub.publish_event(
            ev(sinks=["a", "zzz"]), sinks, self.box, self.noise, "t"),
            "unknown sink")

    def test_same_event_to_two_sinks(self):
        """Provider-neutrality proof: the wp-like adapter and a second
        sink receive the byte-identical canonical event."""
        rec = RecSink("wp-like")
        js = pub.JsonSink(self.tmp / "out.jsonl")
        sinks = {"wp-like": rec, "json": js}
        e = pub.validate_event(ev(kind="milestone", job="j1",
                                  visibility="members"))
        res = pub.publish_event(
            {**e, "sinks": ["wp-like", "json"]}, sinks,
            self.box, self.noise, "t")
        self.assertEqual(res["receipts"]["wp-like"]["status"],
                         "delivered")
        line = json.loads(
            (self.tmp / "out.jsonl").read_text().splitlines()[-1])
        self.assertEqual(rec.events[0], line["event"])
        self.assertEqual(rec.events[0]["event_id"], res["event_id"])

    def test_unrouted_kind_defaults_nothing(self):
        sinks = {"x": RecSink("x")}
        # no default routes match registry names -> empty receipts,
        # event still recorded (not an error — callers pick sinks)
        res = pub.publish_event(ev(), sinks, self.box, self.noise, "t")
        self.assertEqual(res["receipts"], {})


class VisibilityTest(PubTestBase):
    def test_private_never_reaches_members(self):
        mem = RecSink("mem", surface="members")
        prv = RecSink("prv", surface="private")
        sinks = {"mem": mem, "prv": prv}
        res = pub.publish_event(
            ev(sinks=["mem", "prv"]), sinks, self.box, self.noise, "t")
        self.assertEqual(res["receipts"]["mem"]["status"], "skipped")
        self.assertIn("visibility", res["receipts"]["mem"]["reason"])
        self.assertEqual(res["receipts"]["prv"]["status"], "delivered")
        self.assertEqual(len(mem.events), 0)

    def test_public_reaches_all_surfaces(self):
        sinks = {"a": RecSink("a", surface="public"),
                 "b": RecSink("b", surface="members"),
                 "c": RecSink("c", surface="private")}
        res = pub.publish_event(
            ev(visibility="public", sinks=["a", "b", "c"]),
            sinks, self.box, self.noise, "t")
        for r in res["receipts"].values():
            self.assertEqual(r["status"], "delivered")

    def test_sink_capability_kind_and_evidence(self):
        narrow = RecSink("narrow", kinds={"lesson"})
        needev = pub.Sink("needev", surface="private",
                          evidence_required=True)
        needev.publish = lambda e: {"ref": "x"}
        sinks = {"narrow": narrow, "needev": needev}
        res = pub.publish_event(
            ev(kind="progress", sinks=["narrow", "needev"]),
            sinks, self.box, self.noise, "t")
        self.assertEqual(res["receipts"]["narrow"]["status"], "skipped")
        self.assertIn("unsupported", res["receipts"]["narrow"]["reason"])
        self.assertIn("evidence", res["receipts"]["needev"]["reason"])

    def test_capabilities_report(self):
        s = pub.TelegramSink(poster=lambda p: {"ok": True})
        caps = s.capabilities()
        self.assertEqual(caps["surface"], "members")
        self.assertIn("milestone", caps["kinds"])
        self.assertNotIn("progress", caps["kinds"])


class IdempotencyTest(PubTestBase):
    def test_retry_dedupes(self):
        rec = RecSink()
        sinks = {"mock": rec}
        res1 = pub.publish_event(
            ev(sinks=["mock"]), sinks, self.box, self.noise, "t")
        res2 = pub.publish_event(
            ev(sinks=["mock"]), sinks, self.box, self.noise, "t")
        self.assertFalse(res1["deduped"])
        self.assertTrue(res2["deduped"])
        self.assertEqual(len(rec.events), 1)
        self.assertEqual(res2["receipts"]["mock"]["status"], "delivered")

    def test_distinct_keys_deliver(self):
        rec = RecSink()
        sinks = {"mock": rec}
        pub.publish_event(ev(title="one", sinks=["mock"]),
                          sinks, self.box, self.noise, "t")
        pub.publish_event(ev(title="two", sinks=["mock"]),
                          sinks, self.box, self.noise, "t")
        self.assertEqual(len(rec.events), 2)


class OutboxTest(PubTestBase):
    def test_failure_queues_then_drains(self):
        bad = RecSink("flaky", fail=True)
        sinks = {"flaky": bad}
        res = pub.publish_event(
            ev(sinks=["flaky"]), sinks, self.box, self.noise, "t")
        self.assertEqual(res["receipts"]["flaky"]["status"], "queued")
        self.assertEqual(self.box.pending_count(), 1)
        # not due yet
        res = self.box.drain(sinks)
        self.assertEqual(res["pending"], 1)
        # force due: fix the sink and backdate next_at
        bad.fail = False
        entries = self.box._pending()
        entries[0]["next_at"] = 0
        self.box._write_pending(entries)
        res = self.box.drain(sinks)
        self.assertEqual(len(res["delivered"]), 1)
        self.assertEqual(res["pending"], 0)
        self.assertEqual(len(bad.events), 1)
        # delivered receipt merged into delivered.json
        key = pub.validate_event(ev())["idempotency_key"]
        stored = self.box.delivered(key)
        self.assertEqual(stored["receipts"]["flaky"]["via"], "outbox")

    def test_dead_letter_after_cap(self):
        bad = RecSink("dead", fail=True)
        sinks = {"dead": bad}
        pub.publish_event(ev(sinks=["dead"]), sinks,
                          self.box, self.noise, "t")
        for _ in range(pub.Outbox.MAX_ATTEMPTS + 1):
            entries = self.box._pending()
            for e in entries:
                e["next_at"] = 0
            self.box._write_pending(entries)
            self.box.drain(sinks)
        self.assertEqual(self.box.pending_count(), 0)
        dead = (self.tmp / "state" / "dead.jsonl").read_text().splitlines()
        self.assertEqual(len(dead), 1)

    def test_unknown_sink_dead_letters(self):
        bad = RecSink("gone", fail=True)
        pub.publish_event(ev(sinks=["gone"]), {"gone": bad},
                          self.box, self.noise, "t")
        entries = self.box._pending()
        entries[0]["next_at"] = 0
        self.box._write_pending(entries)
        res = self.box.drain({})   # registry lost the sink
        self.assertEqual(res["dead"], 1)


class NoiseTest(PubTestBase):
    def test_progress_throttled_per_topic(self):
        rec = RecSink()
        sinks = {"mock": rec}
        r1 = pub.publish_event(
            ev(job="j1", sinks=["mock"]), sinks, self.box,
            self.noise, "t", now="2026-10-26T10:00:00+00:00")
        self.assertEqual(r1["receipts"]["mock"]["status"], "delivered")
        r2 = pub.publish_event(
            ev(job="j1", title="different title", sinks=["mock"],
               idempotency_key="k2"),
            sinks, self.box, self.noise, "t",
            now="2026-10-26T10:05:00+00:00")
        self.assertEqual(r2["receipts"]["mock"]["status"], "suppressed")
        # a different topic is NOT suppressed — throttle is per topic
        r3 = pub.publish_event(
            ev(job="j2", sinks=["mock"], idempotency_key="k3"),
            sinks, self.box, self.noise, "t",
            now="2026-10-26T10:05:00+00:00")
        self.assertEqual(r3["receipts"]["mock"]["status"], "delivered")

    def test_milestone_not_throttled_force_bypasses(self):
        rec = RecSink()
        sinks = {"mock": rec}
        pub.publish_event(
            ev(kind="milestone", job="j1", sinks=["mock"]),
            sinks, self.box, self.noise, "t")
        r = pub.publish_event(
            ev(kind="milestone", job="j1", sinks=["mock"],
               idempotency_key="k2"),
            sinks, self.box, self.noise, "t")
        self.assertEqual(r["receipts"]["mock"]["status"], "delivered")
        r = pub.publish_event(
            ev(job="j1", sinks=["mock"], idempotency_key="k3",
               force=True),
            sinks, self.box, self.noise, "t")
        self.assertEqual(r["receipts"]["mock"]["status"], "delivered")

    def test_telegram_floor(self):
        posted = []
        tg = pub.TelegramSink(
            url="mock://tg", poster=lambda p: posted.append(p) or {"ok": True})
        sinks = {"telegram": tg}
        ev1 = pub.validate_event(
            ev(kind="alert", title="a1", card="c1", visibility="members"))
        r = pub.publish_event({**ev1, "sinks": ["telegram"]},
                              sinks, self.box, self.noise, "t",
                              now="2026-10-26T10:00:00+00:00")
        self.assertEqual(r["receipts"]["telegram"]["status"], "delivered")
        ev2 = pub.validate_event(
            ev(kind="milestone", title="a2", card="c1",
               visibility="members"))
        r = pub.publish_event({**ev2, "sinks": ["telegram"]},
                              sinks, self.box, self.noise, "t",
                              now="2026-10-26T10:01:00+00:00")
        self.assertEqual(r["receipts"]["telegram"]["status"],
                         "suppressed")
        self.assertEqual(len(posted), 1)

    def test_telegram_render(self):
        e = pub.validate_event(
            ev(kind="news", title="Flood watch upgraded",
               body="Three agencies confirm.", evidence=["http://x"],
               visibility="members"))
        text = pub.TelegramSink.render(e)
        self.assertIn("[DevNest news]", text)
        self.assertIn("Flood watch upgraded", text)
        self.assertIn("http://x", text)


class BoardApiWiringTest(PubTestBase):
    """do_publish in board-api: WP adapter + JsonSink receive the same
    canonical event — WP is only one adapter."""

    @classmethod
    def setUpClass(cls):
        cls.ba = _load("board-api.py")

    def setUp(self):
        super().setUp()
        m = self.ba
        self._saved = {k: getattr(m, k) for k in
                       ("wp_api", "PUB_STATE_DIR", "PUB_TG_URL")}
        m.PUB_STATE_DIR = self.tmp / "pub-state"
        m.PUB_TG_URL = "http://127.0.0.1:1/send"   # closed port

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.ba, k, v)

    def _fake_wp(self):
        posts = []

        def fake(route, data=None, method=None):
            if data is None:
                return []
            posts.append((route, data))
            return {"id": 42}
        self.ba.wp_api = fake
        return posts

    def test_progress_to_job_and_json(self):
        posts = self._fake_wp()
        res = self.ba.do_publish(
            {"kind": "progress", "title": "bench 50%",
             "job": "thonburian-bench", "source": "queue-mgr",
             "visibility": "members", "confidence": "measured",
             "sinks": ["job", "json"]}, "queue-mgr")
        self.assertEqual(res["receipts"]["job"]["status"], "delivered")
        self.assertEqual(res["receipts"]["json"]["status"], "delivered")
        route, payload = posts[-1]
        self.assertEqual(route, "/wp/v2/nest_job")
        self.assertEqual(payload["slug"], "thonburian-bench")
        self.assertEqual(payload["meta"]["status"], "running")
        self.assertEqual(payload["meta"]["event_id"], res["event_id"])
        line = json.loads(
            (self.tmp / "pub-state" / "published.jsonl")
            .read_text().splitlines()[-1])
        self.assertEqual(line["event"]["event_id"], res["event_id"])

    def test_milestone_to_job_board_tg(self):
        posts = self._fake_wp()
        res = self.ba.do_publish(
            {"kind": "milestone", "title": "bench done", "job": "j1",
             "source": "queue-mgr", "visibility": "members"},
            "queue-mgr")
        # default route: job + board + telegram; board skips (no card),
        # telegram queues (relay down) — honest partial delivery
        self.assertEqual(res["receipts"]["job"]["status"], "delivered")
        self.assertEqual(res["receipts"]["board"]["status"], "skipped")
        self.assertEqual(res["receipts"]["telegram"]["status"], "queued")

    def test_news_maps_to_wp_news(self):
        posts = self._fake_wp()
        res = self.ba.do_publish(
            {"kind": "news", "title": "Pilot A passed",
             "body": "Free lane merged with zero tokens.",
             "evidence": ["docs/reports/devnest-free-lane-pilot-a.md"],
             "source": "devin", "visibility": "members"},
            "devin")
        self.assertEqual(res["receipts"]["news"]["status"], "delivered")
        route, payload = posts[-1]
        self.assertEqual(route, "/wp/v2/news")
        self.assertEqual(payload["status"], "private")  # members surface
        self.assertIn("Evidence", payload["content"])
        self.assertIn("devnest-free-lane-pilot-a.md", payload["content"])

    def test_report_to_dossier(self):
        noted = []

        class FakeCRN:
            @staticmethod
            def note(slug, text, lang):
                noted.append((slug, text))
                return {"slug": slug, "line": text, "updated": "u"}
        real_crn = self.ba._crn
        self.ba._crn = lambda: FakeCRN
        try:
            res = self.ba.do_publish(
                {"kind": "report", "title": "session log",
                 "body": "did the thing", "project": "dev-kanban",
                 "source": "devin", "visibility": "members",
                 "sinks": ["report"]}, "devin")
        finally:
            self.ba._crn = real_crn
        self.assertEqual(res["receipts"]["report"]["status"], "delivered")
        self.assertEqual(noted[0][0], "dev-kanban")
        self.assertIn(res["event_id"], noted[0][1])

    def test_sinks_op_lists_capabilities(self):
        res = self.ba.do_publish({"op": "sinks"}, "devin")
        self.assertIn("telegram", res["sinks"])
        self.assertEqual(res["sinks"]["job"]["surface"], "members")
        self.assertTrue(res["sinks"]["news"]["evidence_required"])

    def test_dedupe_across_adapters(self):
        posts = self._fake_wp()
        body = {"kind": "milestone", "title": "done", "job": "j1",
                "source": "q", "visibility": "members",
                "sinks": ["job", "json"]}
        r1 = self.ba.do_publish(dict(body), "q")
        r2 = self.ba.do_publish(dict(body), "q")
        self.assertTrue(r2["deduped"])
        wp_posts = [p for p in posts if p[0] == "/wp/v2/nest_job"]
        self.assertEqual(len(wp_posts), 1)


if __name__ == "__main__":
    unittest.main()
