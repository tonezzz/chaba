#!/usr/bin/env python3
"""Offline unit tests for the card distiller (card-distill-free-lane).

Covers the fixed-slot contract — normalize, frozen-snapshot pseudo-card,
cache keying by (card_id, updated), schema conformance. No network: the
lane chain is stubbed throughout.
"""
import json, os, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "bench" / "card-judgment"))
import distill  # noqa: E402


SNAP = {"title": "T", "priority": "high", "review_kind": "decide",
        "tags": ["infra"], "brief": "b", "spec_present": True,
        "open_requests": [{"ask": "which?"}], "claim": "active",
        "action_status": "queued",
        "comms_tail": [{"at": "2026-01-01", "from": "devin",
                        "text": "did the thing"}]}


class TestNormalize(unittest.TestCase):
    def test_all_slots_present_as_strings(self):
        b = distill._normalize({"needed_move_class": "please decide this",
                                "staleness": "looks dead to me"})
        for s in distill.SLOTS:
            self.assertIsInstance(b[s], str)
        self.assertEqual(b["needed_move_class"], "decide")
        self.assertEqual(b["staleness"], "dead")

    def test_bad_enum_defaults(self):
        b = distill._normalize({"needed_move_class": "??",
                                "staleness": "??"})
        self.assertEqual(b["needed_move_class"], "monitor")
        self.assertEqual(b["staleness"], "stale")

    def test_normalized_brief_matches_schema(self):
        import jsonschema
        schema = json.loads((REPO / "schemas" /
                             "card-distill-slots.schema.json").read_text())
        b = distill._normalize({})
        jsonschema.validate(b, schema)


class TestPseudoCard(unittest.TestCase):
    def test_snapshot_maps_to_card_view(self):
        pc = distill.pseudo_card(SNAP, "card-x")
        self.assertEqual(pc["id"], "card-x")
        self.assertEqual(pc["review_kind"], "decide")
        self.assertEqual(pc["requests"][0]["status"], "open")
        self.assertEqual(pc["claim"]["status"], "active")
        self.assertEqual(pc["comms"][0]["text"], "did the thing")

    def test_snapshot_key_is_content_hash(self):
        k1 = distill.snapshot_key(SNAP)
        k2 = distill.snapshot_key(dict(SNAP))
        self.assertEqual(k1, k2)
        changed = dict(SNAP, title="T2")
        self.assertNotEqual(k1, distill.snapshot_key(changed))


class TestCache(unittest.TestCase):
    def test_sidecar_roundtrip_and_update_keying(self):
        with tempfile.TemporaryDirectory() as td:
            card = {"id": "c1", "updated": "2026-11-09 10:00"}
            calls = []
            orig = distill.distill
            distill.distill = lambda c, l: {**distill._normalize({}),
                                            "_lane": "stub"}
            try:
                b1 = distill.distill_card(card, lanes=[], cache_dir=td)
                calls.append(1)
                # same (id, updated) -> cache hit, no lane call
                b2 = distill.distill_card(card, lanes=[], cache_dir=td)
                self.assertEqual(b1, b2)
                # new updated -> re-distill
                card["updated"] = "2026-11-09 11:00"
                b3 = distill.distill_card(card, lanes=[], cache_dir=td)
                self.assertEqual(b3["_key"], "2026-11-09 11:00")
            finally:
                distill.distill = orig
            with open(os.path.join(td, "c1.json")) as f:
                sidecar = json.load(f)
            self.assertEqual(len(sidecar["entries"]), 2)

    def test_failures_not_cached(self):
        with tempfile.TemporaryDirectory() as td:
            card = {"id": "c2", "updated": "u1"}
            orig = distill.distill
            distill.distill = lambda c, l: {"state": "distill-failed",
                                            "_lane": "none"}
            try:
                distill.distill_card(card, lanes=[], cache_dir=td)
            finally:
                distill.distill = orig
            p = os.path.join(td, "c2.json")
            self.assertFalse(os.path.exists(p))


class TestChain(unittest.TestCase):
    def test_default_lanes_ordered(self):
        env = {"CF_API_ACCOUNT_ID": "a", "CF_API_WORKER_TOKEN": "t",
               "LITELLM_KEY": "k"}
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            names = [n for n, *_ in distill.default_lanes()]
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(names[:2], ["cf-70b", "local-ollama"])
        self.assertIn("or-free", names)
        self.assertIn("flash-lite-free", names)
        self.assertLess(names.index("or-free"),
                        names.index("flash-lite-free"))


if __name__ == "__main__":
    unittest.main()
