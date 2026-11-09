"""Unit tests for the board-api read projection (AUD-1033, card
ops-manual-command-api-mcp-efficiency-audit): GET /cards?<query> and
GET /card/<id> — the filtered/compact read surface that replaces
full-dump fetch + local grep orchestration.

Covers card_query() pure logic (filters, pagination, projection) and
do_GET routing (legacy /cards shape preserved, /card/<id> 200/404/400)
against a real ThreadingHTTPServer on an ephemeral port with
CARDS_JSON pointed at a fixture — no network beyond loopback.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "board_api_reads", REPO / "scripts" / "board" / "board-api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE_CARDS = [
    {"id": "c-one", "title": "One", "column": "doing", "ref": "OPS-1",
     "updated": "2026-10-29 08:00", "priority": "high",
     "action": {"status": "queued", "repo": "chaba", "labels": ["x"]},
     "brief": "first", "spec": "S" * 5000, "comms": [{"at": "t", "from": "a", "text": "hi"}]},
    {"id": "c-two", "title": "Two", "column": "doing",
     "updated": "2026-10-30 09:00", "priority": "low",
     "action": {"status": "running"}, "blocked_by": "c-one"},
    {"id": "c-three", "title": "Three", "column": "done",
     "updated": "2026-10-31 10:00", "action": {"status": "closed"}},
    {"id": "c-four", "title": "Four", "column": "backlog"},
]


class CardQueryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def q(self, **params):
        return self.mod.card_query(FIXTURE_CARDS,
                                   {k: [str(v)] for k, v in params.items()})

    def test_id_filter(self):
        r = self.q(id="c-one")
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["cards"][0]["id"], "c-one")

    def test_column_filter(self):
        self.assertEqual(self.q(column="doing")["total"], 2)
        self.assertEqual(self.q(column="review")["total"], 0)

    def test_action_status_filter(self):
        r = self.q(action_status="queued")
        self.assertEqual([c["id"] for c in r["cards"]], ["c-one"])

    def test_since_filter(self):
        self.assertEqual(self.q(since="2026-10-30")["total"], 2)
        self.assertEqual(self.q(since="2026-10-30 09:00")["total"], 2)
        self.assertEqual(self.q(since="2999-01-01")["total"], 0)

    def test_combined_filters(self):
        r = self.q(column="doing", since="2026-10-30")
        self.assertEqual([c["id"] for c in r["cards"]], ["c-two"])

    def test_fields_projection(self):
        r = self.mod.card_query(FIXTURE_CARDS, {"fields": ["id,title"]})
        self.assertEqual(r["cards"][0], {"id": "c-one", "title": "One"})

    def test_fields_unknown_ignored(self):
        r = self.mod.card_query(
            FIXTURE_CARDS, {"fields": ["id,nosuchfield"]})
        self.assertEqual(r["cards"][0], {"id": "c-one"})

    def test_compact_projection(self):
        r = self.q(compact="1")
        want = set(self.mod.COMPACT_FIELDS)
        for c in r["cards"]:
            self.assertLessEqual(set(c), want)
        self.assertNotIn("spec", r["cards"][0])
        self.assertNotIn("comms", r["cards"][0])

    def test_compact_exposes_action_status(self):
        # OPS-1107 — queue state must survive the slim projection or
        # client-side claimable scans see "no queued cards".
        r = self.q(compact="1")
        by_id = {c["id"]: c for c in r["cards"]}
        self.assertEqual(by_id["c-one"]["action_status"], "queued")
        self.assertEqual(by_id["c-two"]["action_status"], "running")
        self.assertEqual(by_id["c-three"]["action_status"], "closed")
        self.assertIsNone(by_id["c-four"]["action_status"])
        self.assertNotIn("action", by_id["c-one"])

    def test_fields_action_status(self):
        r = self.mod.card_query(
            FIXTURE_CARDS, {"fields": ["id,action_status"]})
        self.assertEqual(r["cards"][0],
                         {"id": "c-one", "action_status": "queued"})

    def test_fields_action_status_missing(self):
        r = self.mod.card_query(
            FIXTURE_CARDS, {"id": ["c-four"], "fields": ["id,action_status"]})
        self.assertIsNone(r["cards"][0]["action_status"])

    def test_compact_beats_fields(self):
        r = self.mod.card_query(
            FIXTURE_CARDS, {"compact": ["1"], "fields": ["spec"]})
        self.assertNotIn("spec", r["cards"][0])

    def test_pagination(self):
        r = self.q(limit="2")
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["total"], 4)
        self.assertTrue(r["truncated"])
        r2 = self.q(limit="2", offset="2")
        self.assertFalse(r2["truncated"])
        ids = [c["id"] for c in r["cards"]] + [c["id"] for c in r2["cards"]]
        self.assertEqual(ids, ["c-one", "c-two", "c-three", "c-four"])

    def test_limit_cap(self):
        r = self.q(limit="999999")
        self.assertEqual(r["count"], 4)

    def test_bad_numbers(self):
        r = self.q(limit="abc", offset="xyz")
        self.assertEqual(r["count"], 4)
        self.assertEqual(r["offset"], 0)

    def test_missing_cards_empty_not_error(self):
        r = self.mod.card_query([], {"column": ["doing"]})
        self.assertEqual(r, {"ok": True, "count": 0, "total": 0,
                             "offset": 0, "truncated": False, "cards": []})


class GetRoutingTest(unittest.TestCase):
    """do_GET over loopback: fixture cards.json via CARDS_JSON patch."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()
        cls.tmp = tempfile.TemporaryDirectory()
        fixture = Path(cls.tmp.name) / "cards.json"
        fixture.write_text(json.dumps(
            {"generated": "2026-10-31 08:00", "page_version": 1,
             "columns": [], "cards": FIXTURE_CARDS}))
        cls._saved = cls.mod.CARDS_JSON
        cls._saved_card_dir = cls.mod.CARD_DIR
        cls._saved_lock = cls.mod.LOCK
        cls.mod.LOCK = Path(cls.tmp.name) / "board-api.lock"
        cls.mod.CARDS_JSON = fixture
        cls.mod.CARD_DIR = Path(cls.tmp.name) / "cards"
        cls.mod.CARD_DIR.mkdir()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), cls.mod.H)
        cls.port = cls.srv.server_address[1]
        cls.th = threading.Thread(target=cls.srv.serve_forever,
                                  daemon=True)
        cls.th.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.mod.CARDS_JSON = cls._saved
        cls.mod.CARD_DIR = cls._saved_card_dir
        cls.mod.LOCK = cls._saved_lock
        cls.tmp.cleanup()

    def setUp(self):
        for path in self.mod.CARD_DIR.glob("*.yml"):
            path.unlink()
        for card in FIXTURE_CARDS:
            (self.mod.CARD_DIR / f"{card['id']}.yml").write_text(json.dumps(card))

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health(self):
        st, body = self.get("/health")
        self.assertEqual((st, body), (200, {"ok": True}))

    def test_bare_cards_legacy_shape(self):
        st, body = self.get("/cards")
        self.assertEqual(st, 200)
        self.assertIn("cards", body)
        self.assertIn("generated", body)
        self.assertNotIn("total", body)  # legacy passthrough, no envelope
        self.assertEqual(len(body["cards"]), 4)

    def test_cards_query_envelope(self):
        st, body = self.get("/cards?column=doing&compact=1")
        self.assertEqual(st, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["count"], 2)
        self.assertNotIn("spec", body["cards"][0])

    def test_single_card(self):
        st, body = self.get("/card/c-one")
        self.assertEqual(st, 200)
        self.assertEqual(body["card"]["id"], "c-one")
        self.assertIn("spec", body["card"])

    def test_single_card_projected(self):
        st, body = self.get("/card/c-one?fields=id,updated")
        self.assertEqual(body["card"], {"id": "c-one",
                                        "updated": "2026-10-29 08:00"})

    def test_single_card_404(self):
        st, body = self.get("/card/nosuch")
        self.assertEqual(st, 404)
        self.assertEqual(body["id"], "nosuch")

    def test_card_no_id_400(self):
        st, body = self.get("/card")
        self.assertEqual(st, 400)
        self.assertIn("hint", body)

    def test_post_comment_is_immediately_visible_without_render(self):
        body = json.dumps({"id": "c-one", "from": "devin", "text": "fresh canonical comment"}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/comment", data=body,
                                     headers={"Content-Type": "application/json"})
        with mock.patch.object(self.mod, "_commit_write"), mock.patch.object(self.mod, "render_async"):
            with urllib.request.urlopen(req, timeout=5) as response:
                self.assertTrue(json.load(response)["ok"])
        for path in ("/cards?id=c-one", "/card/c-one"):
            status, response = self.get(path)
            card = response["card"] if "card" in response else response["cards"][0]
            self.assertEqual(status, 200)
            self.assertEqual(card["comms"][-1]["text"], "fresh canonical comment")

    def test_canonical_new_deleted_and_updated_cards_ignore_stale_projection(self):
        self.get("/cards")
        path = self.mod.CARD_DIR / "c-one.yml"
        card = dict(FIXTURE_CARDS[0], column="review")
        card.pop("action")
        path.write_text(json.dumps(card))
        (self.mod.CARD_DIR / "c-four.yml").unlink()
        (self.mod.CARD_DIR / "new-card.yml").write_text(json.dumps({"id": "new-card", "title": "New", "column": "review"}))
        status, result = self.get("/cards?column=review")
        self.assertEqual(status, 200)
        self.assertEqual({c["id"] for c in result["cards"]}, {"c-one", "new-card"})
        self.assertNotIn("action", next(c for c in result["cards"] if c["id"] == "c-one"))
        self.assertEqual(self.get("/card/c-four")[0], 404)

    def test_corrupt_canonical_card_fails_explicitly_not_stale_or_empty(self):
        (self.mod.CARD_DIR / "c-one.yml").write_text("bad: [")
        for path in ("/cards?column=doing", "/card/c-one"):
            self.assertEqual(self.get(path)[0], 503)

    def test_missing_render_does_not_hide_canonical_cards(self):
        with mock.patch.object(self.mod, "CARDS_JSON", Path(self.tmp.name) / "absent.json"):
            status, response = self.get("/cards?id=c-one")
            self.assertEqual(status, 200)
            self.assertEqual(response["cards"][0]["id"], "c-one")

    def test_queue_still_works(self):
        st, body = self.get("/queue")
        self.assertEqual(st, 200)
        self.assertTrue(body.get("ok"))


if __name__ == "__main__":
    unittest.main()
