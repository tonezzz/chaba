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

    def test_mediawiki_sink_login_edit_and_metadata(self):
        calls = []

        def fake_api(params, post=False):
            calls.append((dict(params), post))
            if params.get("type") == "login":
                return {"query": {"tokens": {"logintoken": "login-token"}}}
            if params.get("action") == "login":
                return {"login": {"result": "Success", "lgusername": "Ada"}}
            if params.get("meta") == "tokens":
                return {"query": {"tokens": {"csrftoken": "csrf-token"}}}
            return {"edit": {"result": "Success", "pageid": 7,
                              "newrevid": 8}}

        sink = pub.MediaWikiSink(
            "https://wiki.example/api.php", "ada", "secret",
            api=fake_api)
        e = pub.validate_event(ev(
            kind="news", title="Thailand AI update", body="A test story.",
            evidence=["https://example/source"], confidence="verified",
            visibility="public", meta={
                "wiki_title": "News/Countries/Thailand/AI/Test",
                "summary": "Verified Thailand AI test story.",
                "geo_scope": "country", "country": "Thailand",
                "region": "Asia", "topic": "Artificial Intelligence",
            }))
        result = sink.publish(e)
        self.assertEqual(result["pageid"], 7)
        self.assertEqual(result["revid"], 8)
        edit = calls[-1][0]
        self.assertEqual(edit["title"], "News/Countries/Thailand/AI/Test")
        self.assertIn("Thailand AI update", edit["text"])
        self.assertIn("Quick summary:", edit["text"])
        self.assertIn("Category:News/Geography/Thailand", edit["text"])
        self.assertTrue(calls[-1][1])

    def test_mediawiki_sink_is_public_only(self):
        sink = pub.MediaWikiSink(
            "https://wiki.example/api.php", "ada", "secret",
            api=lambda *_: {})
        e = pub.validate_event(ev(
            kind="news", title="private", body="test",
            evidence=["https://example/source"], visibility="members"))
        reason = sink.check(e)
        self.assertIn("visibility", reason)

    def test_mediawiki_private_sink_accepts_private_namespace_only(self):
        sink = pub.MediaWikiSink(
            "https://wiki.example/api.php", "ada", "secret",
            api=lambda *_: {}, name="wiki-private", surface="private",
            namespace_prefix="PrivateNews:")
        private = pub.validate_event(ev(
            kind="news", title="private", body="test",
            evidence=["https://example/source"], visibility="private",
            meta={"wiki_title": "PrivateNews/Countries/Thailand/test",
                  "summary": "Private review test."}))
        self.assertIsNone(sink.check(private))
        public = pub.validate_event(ev(
            kind="news", title="public", body="test",
            evidence=["https://example/source"], visibility="public",
            confidence="verified",
            meta={"wiki_title": "News/Countries/Thailand/test",
                  "summary": "Public test."}))
        self.assertIn("private events only", sink.check(public))


class HtmlToWikitextTest(unittest.TestCase):
    """Lesson-body HTML -> wikitext converter
    (card wiki-member-knowledge-surface-migrate-wp-3a1cf2)."""

    def test_basic_markup(self):
        html = ("<p>Intro <strong>bold</strong> and <em>it</em>.</p>"
                "<h3>ไทย</h3><p>ไทย body</p><hr>"
                "<ul><li>one</li><li>two</li></ul>"
                "<p><a href='https://x/y'>the link</a></p>")
        wt = pub.html_to_wikitext(html)
        self.assertIn("'''bold'''", wt)
        self.assertIn("''it''", wt)
        self.assertIn("=== ไทย ===", wt)
        self.assertIn("----", wt)
        self.assertIn("* one\n* two", wt)
        self.assertIn("[https://x/y the link]", wt)

    def test_nested_lists_and_ol(self):
        html = ("<ol><li>a<ul><li>a1</li><li>a2</li></ul></li>"
                "<li>b</li></ol>")
        wt = pub.html_to_wikitext(html)
        self.assertIn("# a", wt)
        self.assertIn("#* a1\n#* a2", wt)
        self.assertIn("# b", wt)

    def test_bare_url_link_and_h1(self):
        wt = pub.html_to_wikitext(
            "<h1>T</h1><p><a href='https://x/y'>https://x/y</a></p>")
        self.assertTrue(wt.startswith("== T =="))
        self.assertIn("[https://x/y]", wt)

    def test_script_style_dropped_unknown_flattened(self):
        wt = pub.html_to_wikitext(
            "<p>keep<style>.x{}</style><script>bad()</script>"
            "<marquee>me</marquee></p>")
        self.assertIn("keep", wt)
        self.assertIn("me", wt)
        self.assertNotIn("bad()", wt)
        self.assertNotIn(".x{}", wt)


class LessonWikiTitleTest(unittest.TestCase):
    def test_readable_title(self):
        self.assertEqual(pub.lesson_wiki_title("ada-nest-map"),
                         "Education:Ada-Nest-Map")
        self.assertEqual(pub.lesson_wiki_title("cloud object storage"),
                         "Education:Cloud Object Storage")
        self.assertEqual(pub.lesson_wiki_title("WP REST API"),
                         "Education:WP REST API")
        # forbidden title chars fold to spaces, md5 slug never leaks
        t = pub.lesson_wiki_title("a<b>[c]|d_{e}")
        self.assertNotRegex(t, r"[#<>\[\]|{}_]")


class WikiLessonSinkTest(PubTestBase):
    """WikiLessonSink — protected Education: namespace adapter."""

    def _sink(self, calls):
        def fake_api(params, post=False):
            calls.append((dict(params), post))
            if params.get("type") == "login":
                return {"query": {"tokens": {"logintoken": "lt"}}}
            if params.get("action") == "login":
                return {"login": {"result": "Success"}}
            if params.get("meta") == "tokens":
                return {"query": {"tokens": {"csrftoken": "ct"}}}
            return {"edit": {"result": "Success", "pageid": 9,
                             "newrevid": 10}}
        return pub.WikiLessonSink(
            "https://wiki.example/api.php", "ada", "secret",
            api=fake_api)

    def _ev(self, body="<p>Block storage <strong>basics</strong>.</p>",
            **meta):
        m = {"topic": "cloud object storage", "level": "working",
             "status": "open", "next_review": "2026-11-15",
             "wiki_title": "Education:Cloud Object Storage"}
        m.update(meta)
        return pub.validate_event(ev(
            kind="lesson", title="cloud object storage",
            body=body, visibility="private", meta=m))

    def test_publish_edit_and_metadata(self):
        calls = []
        r = self._sink(calls).publish(self._ev())
        self.assertEqual(r["pageid"], 9)
        edit = calls[-1][0]
        self.assertEqual(edit["title"], "Education:Cloud Object Storage")
        self.assertIn("{{แม่แบบ:Education", edit["text"])
        self.assertIn("|level=working", edit["text"])
        self.assertIn("|next_review=2026-11-15", edit["text"])
        self.assertIn("'''basics'''", edit["text"])   # html converted
        self.assertIn("[[Category:Education/Level/working]]",
                      edit["text"])
        self.assertIn("[[Category:Education/Topics/"
                      "cloud-object-storage]]", edit["text"])

    def test_wikitext_format_passthrough(self):
        calls = []
        self._sink(calls).publish(
            self._ev(format="wikitext",
                     body="already '''wiki''' text"))
        self.assertIn("already '''wiki''' text", calls[-1][0]["text"])

    def test_title_derives_from_topic(self):
        calls = []
        e = self._ev()
        del e["meta"]["wiki_title"]
        self._sink(calls).publish(e)
        self.assertEqual(calls[-1][0]["title"],
                         "Education:Cloud Object Storage")

    def test_gates(self):
        sink = self._sink([])
        # wrong kind
        news = pub.validate_event(ev(
            kind="news", title="n", body="b",
            evidence=["https://x"], visibility="private",
            meta={"wiki_title": "Education:X"}))
        self.assertIn("unsupported", sink.check(news))
        # members/public can't reach a private namespace
        mem = self._ev()
        mem["visibility"] = "members"
        self.assertIn("private events only", sink.check(mem))
        # title outside the namespace
        bad = self._ev(wiki_title="News/Cloud")
        try:
            sink._title(bad)
        except pub.Skip as e:
            self.assertIn("Education:", str(e))
        else:
            raise AssertionError("expected Skip")


class ReportWikiTitleTest(unittest.TestCase):
    def test_living_page_title(self):
        self.assertEqual(
            pub.report_wiki_title("usage-ledger", "rolling-14d"),
            "Reports:Usage-Ledger/rolling-14d")
        self.assertEqual(pub.report_wiki_title("usage-ledger"),
                         "Reports:Usage-Ledger")

    def test_forbidden_chars_fold(self):
        t = pub.report_wiki_title("a<b>", "p|x_y")
        self.assertNotRegex(t, r"[#<>\[\]|{}_]")


class WikiReportSinkTest(PubTestBase):
    """WikiReportSink — protected Reports: namespace adapter
    (card wiki-member-knowledge-surface-migrate-wp-3a1cf2)."""

    def _sink(self, calls):
        def fake_api(params, post=False):
            calls.append((dict(params), post))
            if params.get("type") == "login":
                return {"query": {"tokens": {"logintoken": "lt"}}}
            if params.get("action") == "login":
                return {"login": {"result": "Success"}}
            if params.get("meta") == "tokens":
                return {"query": {"tokens": {"csrftoken": "ct"}}}
            return {"edit": {"result": "Success", "pageid": 11,
                             "newrevid": 12}}
        return pub.WikiReportSink(
            "https://wiki.example/api.php", "ada", "secret",
            api=fake_api)

    def _ev(self, body="<p>Rolling usage <strong>ledger</strong>.</p>",
            **meta):
        m = {"report_type": "usage-ledger", "period": "rolling-14d",
             "source_key": "idc03-usage-feed",
             "wiki_title": "Reports:Usage-Ledger/rolling-14d"}
        m.update(meta)
        return pub.validate_event(ev(
            kind="report", title="usage-ledger", body=body,
            visibility="private", meta=m))

    def test_publish_edit_and_metadata(self):
        calls = []
        r = self._sink(calls).publish(self._ev())
        self.assertEqual(r["pageid"], 11)
        edit = calls[-1][0]
        self.assertEqual(edit["title"],
                         "Reports:Usage-Ledger/rolling-14d")
        self.assertIn("{{แม่แบบ:Report", edit["text"])
        self.assertIn("|report_type=usage-ledger", edit["text"])
        self.assertIn("|period=rolling-14d", edit["text"])
        self.assertIn("|source_key=idc03-usage-feed", edit["text"])
        self.assertIn("'''ledger'''", edit["text"])   # html converted
        self.assertIn("[[Category:Reports/Type/usage-ledger]]",
                      edit["text"])

    def test_wikitext_format_passthrough(self):
        calls = []
        self._sink(calls).publish(
            self._ev(format="wikitext",
                     body="already '''wiki''' text"))
        self.assertIn("already '''wiki''' text", calls[-1][0]["text"])

    def test_title_derives_from_report_meta(self):
        calls = []
        e = self._ev()
        del e["meta"]["wiki_title"]
        self._sink(calls).publish(e)
        self.assertEqual(calls[-1][0]["title"],
                         "Reports:Usage-Ledger/rolling-14d")

    def test_gates(self):
        sink = self._sink([])
        lesson = pub.validate_event(ev(
            kind="lesson", title="l", body="b", visibility="private",
            meta={"wiki_title": "Reports:X"}))
        self.assertIn("unsupported", sink.check(lesson))
        mem = self._ev()
        mem["visibility"] = "members"
        self.assertIn("private events only", sink.check(mem))
        bad = self._ev(wiki_title="Education:X")
        try:
            sink._title(bad)
        except pub.Skip as e:
            self.assertIn("Reports:", str(e))
        else:
            raise AssertionError("expected Skip")


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
                       ("wp_api", "PUB_STATE_DIR", "PUB_TG_URL",
                        "WIKI_ENV_FILE", "WIKI_API_CALL")}
        m.PUB_STATE_DIR = self.tmp / "pub-state"
        m.PUB_TG_URL = "http://127.0.0.1:1/send"   # closed port
        m.WIKI_ENV_FILE = self.tmp / "no-wiki.env"  # absent by default
        m.WIKI_API_CALL = None

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

    def _wiki_env(self, extra=""):
        env = self.tmp / "wiki.env"
        env.write_text(
            "WIKI_HOST=https://wiki.example\nWIKI_USER=ada\n"
            f"WIKI_PASSWORD=secret\n{extra}")
        self.ba.WIKI_ENV_FILE = env

    def test_wiki_education_sink_registers(self):
        self._wiki_env()
        res = self.ba.do_publish({"op": "sinks"}, "devin")
        s = res["sinks"]["wiki-education"]
        self.assertEqual(s["kinds"], ["lesson"])
        self.assertEqual(s["surface"], "private")

    def test_do_lesson_dual_write_behind_flag(self):
        self._wiki_env("WIKI_EDUCATION_WRITE=dual\n")
        posts = []
        self.ba.wp_api = lambda route, data=None, method=None: (
            posts.append((route, data)) or {"id": 42} if data else [])
        self.ba._gemini_thai = lambda c: None
        sent = []

        class FakeSink:
            def __init__(self, api, u, p):
                sent.append(api)

            def publish(self, ev):
                sent.append(ev)
                return {"ref": "wiki:x"}

        real = self.ba.pub.WikiLessonSink
        self.ba.pub.WikiLessonSink = FakeSink
        try:
            r = self.ba.do_lesson(
                {"topic": "wiki dual write", "content": "<p>c</p>",
                 "no_th": True}, "devin")
        finally:
            self.ba.pub.WikiLessonSink = real
        self.assertEqual(r["wiki"]["status"], "delivered")
        self.assertEqual(sent[0], "https://wiki.example/api.php")
        self.assertEqual(sent[1]["meta"]["wiki_title"],
                         "Education:Wiki Dual Write")
        # flag off -> no wiki key at all
        self._wiki_env("WIKI_EDUCATION_WRITE=off\n")
        r = self.ba.do_lesson(
            {"topic": "wiki dual write", "content": "<p>c</p>",
             "no_th": True}, "devin")
        self.assertNotIn("wiki", r)

    def test_wiki_reports_sink_registers(self):
        self._wiki_env()
        res = self.ba.do_publish({"op": "sinks"}, "devin")
        s = res["sinks"]["wiki-reports"]
        self.assertEqual(s["kinds"], ["report"])
        self.assertEqual(s["surface"], "private")

    def _fake_wiki_api(self, calls, namespaces=()):
        def fake(params, post=False):
            calls.append((dict(params), post))
            if params.get("siprop") == "namespaces":
                return {"query": {"namespaces": {
                    str(i): {"id": i, "*": n, "canonical": n}
                    for i, n in enumerate(namespaces)}}}
            if params.get("type") == "login":
                return {"query": {"tokens": {"logintoken": "lt"}}}
            if params.get("action") == "login":
                return {"login": {"result": "Success"}}
            if params.get("meta") == "tokens":
                return {"query": {"tokens": {"csrftoken": "ct"}}}
            if params.get("action") == "edit":
                return {"edit": {"result": "Success", "pageid": 20,
                                 "newrevid": 21}}
            return {}
        self.ba.WIKI_API_CALL = fake

    def test_wiki_page_template_write(self):
        self._wiki_env()
        calls = []
        self._fake_wiki_api(calls)
        r = self.ba.do_wiki_page(
            {"title": "แม่แบบ:Education", "wikitext": "{| x |}"},
            "devin")
        self.assertEqual(r["action"], "success")
        edit = calls[-1][0]
        self.assertEqual(edit["title"], "แม่แบบ:Education")
        # template writes never consult the namespace table
        self.assertFalse(any(c[0].get("siprop") == "namespaces"
                             for c in calls))

    def test_wiki_page_rejects_unlisted_title(self):
        self._wiki_env()
        calls = []
        self._fake_wiki_api(calls)
        for bad in ("News/x", "PrivateNews:x", "Main Page",
                    "Template:NewsReport"):
            try:
                self.ba.do_wiki_page(
                    {"title": bad, "wikitext": "x"}, "devin")
            except ValueError as e:
                self.assertIn("not allowed", str(e))
            else:
                raise AssertionError(f"{bad} should be refused")
        self.assertFalse(calls)     # nothing reached the wiki

    def test_wiki_page_ns_gate_before_localsettings(self):
        self._wiki_env()
        calls = []
        # Education not yet registered -> refuse, don't litter main ns
        self._fake_wiki_api(calls, namespaces=["Template"])
        try:
            self.ba.do_wiki_page(
                {"title": "Education:Index", "wikitext": "x"}, "devin")
        except ValueError as e:
            self.assertIn("not registered", str(e))
        else:
            raise AssertionError("expected namespace gate")
        # registered -> write goes through
        calls.clear()
        self._fake_wiki_api(calls, namespaces=["Template", "Education"])
        r = self.ba.do_wiki_page(
            {"title": "Education:Index", "wikitext": "x"}, "devin")
        self.assertEqual(r["wiki_title"], "Education:Index")

    def test_report_wp_read_modes(self):
        posts = []

        def fake(route, data=None, method=None):
            posts.append(route)
            if "slug=" in route:
                return [{"slug": "usage-ledger",
                         "title": {"rendered": "Usage"},
                         "content": {"rendered": "<p>c</p>"},
                         "meta": {"report_type": "usage-ledger"},
                         "modified": "2026-11-06", "status": "private"}]
            return [{"slug": "usage-ledger",
                     "title": {"rendered": "Usage"},
                     "meta": {"report_type": "usage-ledger",
                              "period": "rolling-14d",
                              "source_key": "idc03-usage-feed"},
                     "modified": "2026-11-06", "status": "private"}]
        self.ba.wp_api = fake
        r = self.ba.do_report({"mode": "wp-list"}, "devin")
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["reports"][0]["report_type"], "usage-ledger")
        self.assertIn("/wp/v2/report", posts[0])
        g = self.ba.do_report({"mode": "wp-get", "slug": "usage-ledger"},
                              "devin")
        self.assertEqual(g["content"], "<p>c</p>")
        try:
            self.ba.do_report({"mode": "wp-get"}, "devin")
        except ValueError as e:
            self.assertIn("slug", str(e))
        else:
            raise AssertionError("expected slug required")

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
