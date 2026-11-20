"""Tests for scripts/board/host_status.py — the live-first host answer
(card ada-status-live-state-preference, OPS-1045 miss).

The DONE-CONDITION: a host-status ask must return live probe data or a
freshness-tagged board answer, and the telemetry-vs-board contradiction
case must be covered. These tests pin all three rules:

  1. live surfaces (heartbeat probe, nest-mgr page, runner claims) are
     queried before board records and lead the answer;
  2. every board-derived claim carries an "as of Xh ago" tag;
  3. offline-vs-live / disk-figure disagreements are reported as
     CONFLICTs with both sides shown.
"""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime

from scripts.board.host_status import (
    age_str, as_of, board_records, canon_host, detect_conflicts,
    host_status, live_probe, nest_page, processing, _parse_ts)


NOW = time.time()


def _ago(seconds: float) -> str:
    """Card-comm `at` in the board's local-naive convention."""
    return datetime.fromtimestamp(NOW - seconds).strftime(
        "%Y-%m-%d %H:%M")


def hb_doc(body: dict) -> dict:
    return {"contentMd": json.dumps(body)}


def kk_heartbeat(**kw) -> dict:
    body = {"host": "KKs-Mac-Studio", "ts": NOW - 240, "ollama_ok": True,
            "disk_free_gb": 92.0, "load_1m": 1.2}
    body.update(kw)
    return hb_doc(body)


STALE_KK_CARD = {
    "id": "adobe-stock-kk-mac-render-poc",
    "title": "Adobe Stock KK-Mac supervised image-render POC pack",
    "column": "review",
    "comms": [
        {"at": _ago(30 * 3600), "from": "devin",
         "text": "[KNB-1098] Blocked twice over: kk-mac disk at 15GiB "
                 "(below 30GiB floor) AND host offline 22h+. Needs "
                 "space freed on kk-mac when it returns."},
        {"at": _ago(10 * 60), "from": "devin",
         "text": "kk-mac render staged and preflight-ready"},
    ],
}


class CanonHostTest(unittest.TestCase):
    def test_kk_mac_aliases(self):
        for s in ("kk-mac", "kk_mac", "KK-Mac", "kk mac",
                  "KKs-Mac-Studio", "kks-mac-studio.local", "kk-imac",
                  "kkmac"):
            self.assertEqual(canon_host(s), "kk-mac", s)

    def test_kk_macbook_is_not_kk_mac(self):
        self.assertEqual(canon_host("kk-macbook"), "kk-macbook")
        self.assertEqual(canon_host("tony-macbook"), "tony-macbook")

    def test_unknown_host_passthrough(self):
        self.assertEqual(canon_host("mn01"), "mn01")
        self.assertEqual(canon_host("weird host"), "weird-host")


class LiveProbeTest(unittest.TestCase):
    def test_kk_mac_uses_lane_snapshot(self):
        live = live_probe("kk-mac",
                          heartbeat_docs=[kk_heartbeat()], now=NOW)
        self.assertTrue(live["fetched"])
        self.assertTrue(live["online"])
        self.assertTrue(live["eligible"])
        self.assertEqual(live["disk_free_gb"], 92.0)
        self.assertEqual(live["source"], "kk_mac_lane_probe")
        self.assertAlmostEqual(live["heartbeat_age_s"], 240, delta=2)

    def test_generic_host_reads_heartbeat_collection(self):
        docs = [hb_doc({"host": "tony-omen", "ts": NOW - 120,
                        "disk_free_gb": 300, "ollama_ok": True})]
        live = live_probe("tony-omen", heartbeat_docs=docs, now=NOW)
        self.assertTrue(live["online"])
        self.assertEqual(live["disk_free_gb"], 300)

    def test_stale_heartbeat_is_not_online(self):
        docs = [hb_doc({"host": "tony-omen", "ts": NOW - 7200})]
        live = live_probe("tony-omen", heartbeat_docs=docs, now=NOW)
        self.assertTrue(live["fetched"])
        self.assertFalse(live["online"])

    def test_missing_heartbeat(self):
        live = live_probe("mn01", heartbeat_docs=[], now=NOW)
        self.assertTrue(live["fetched"])
        self.assertIsNone(live["online"])

    def test_probe_failure_fails_soft(self):
        live = live_probe("tony-omen", ops_url="http://127.0.0.1:1/v1",
                          now=NOW)
        self.assertFalse(live["fetched"])
        self.assertIn("error", live)


class BoardRecordTest(unittest.TestCase):
    def test_records_carry_age_tags(self):
        recs = board_records([STALE_KK_CARD], "kk-mac", now=NOW)
        self.assertEqual(len(recs), 2)
        self.assertIn("as of", recs[0]["as_of"])
        # newest first: the 10-minute-old comm leads
        self.assertIn("staged and preflight-ready", recs[0]["text"])
        self.assertLess(recs[0]["age_s"], recs[1]["age_s"])

    def test_kk_mac_token_boundaries(self):
        card = {"id": "c", "comms": [
            {"at": _ago(60), "from": "x",
             "text": "kk-macbook battery low"}]}
        self.assertEqual(board_records([card], "kk-mac", now=NOW), [])
        self.assertEqual(
            len(board_records([card], "kk-macbook", now=NOW)), 1)

    def test_processing_lists_running_claims(self):
        cards = [
            {"id": "a1", "title": "job one",
             "action": {"status": "running", "runner": "tony-omen"},
             "claim": {"since": _ago(300)}},
            {"id": "a2", "action": {"status": "running",
                                    "runner": "idc03"}},
            {"id": "a3", "action": {"status": "queued"}},
        ]
        proc = processing(cards, "tony-omen", now=NOW)
        self.assertEqual([p["card"] for p in proc], ["a1"])
        self.assertIn("as of", proc[0]["as_of"])


class ConflictTest(unittest.TestCase):
    """The OPS-1045 shape: card comms claim offline+15GiB while the
    live probe says eligible with 92GiB."""

    def setUp(self):
        self.live = live_probe(
            "kk-mac", heartbeat_docs=[kk_heartbeat()], now=NOW)
        self.recs = board_records([STALE_KK_CARD], "kk-mac", now=NOW)
        self.conflicts = detect_conflicts(self.recs, self.live)
        self.kinds = {c["kind"] for c in self.conflicts}

    def test_offline_vs_live_flagged(self):
        self.assertIn("offline_vs_live", self.kinds)
        c = next(x for x in self.conflicts
                 if x["kind"] == "offline_vs_live")
        self.assertEqual(c["board"]["card"],
                         "adobe-stock-kk-mac-render-poc")
        self.assertIn("30h", c["board"]["as_of"])
        self.assertIn("online", c["live"])

    def test_disk_disagree_flagged(self):
        self.assertIn("disk_disagree", self.kinds)
        c = next(x for x in self.conflicts
                 if x["kind"] == "disk_disagree")
        self.assertEqual(c["board"]["figure_gb"], 15.0)
        self.assertIn("92", c["live"])

    def test_blocked_vs_eligible_flagged(self):
        self.assertIn("blocked_vs_eligible", self.kinds)

    def test_no_conflict_when_records_agree(self):
        card = {"id": "c", "comms": [
            {"at": _ago(60), "from": "x",
             "text": "kk-mac online and eligible, disk 92GiB free"}]}
        recs = board_records([card], "kk-mac", now=NOW)
        self.assertEqual(detect_conflicts(recs, self.live), [])

    def test_no_conflict_without_live(self):
        self.assertEqual(
            detect_conflicts(self.recs, {"fetched": False}), [])

    def test_older_claim_still_conflict_checked(self):
        """The misleading record may sit outside the top-5 mentions —
        latest_claim scans deeper so it is still tagged + flagged."""
        noisy = [{"at": _ago(60 + i * 60), "from": "x",
                  "text": f"kk-mac primer note #{i} about widgets"}
                 for i in range(6)]
        card = {"id": "c", "comms": noisy + STALE_KK_CARD["comms"][:1]}
        out = host_status(
            "kk-mac", now=NOW, cards=[card],
            heartbeat_docs=[kk_heartbeat()], nest_docs=[])
        self.assertIn("offline_vs_live",
                      {c["kind"] for c in out["conflicts"]})
        self.assertIn("newest board host-state claim", out["answer"])
        self.assertIn("as of", out["answer"])


class ComposeTest(unittest.TestCase):
    def test_live_answer_leads_and_conflict_flagged(self):
        out = host_status(
            "kk-mac", now=NOW, cards=[STALE_KK_CARD],
            heartbeat_docs=[kk_heartbeat()], nest_docs=[])
        self.assertTrue(out["ok"])
        self.assertEqual(out["confidence"], "live")
        self.assertTrue(out["contradiction"])
        ans = out["answer"]
        # live telemetry leads the answer
        self.assertTrue(ans.startswith("kk-mac is ONLINE"), ans)
        self.assertIn("eligible", ans)
        self.assertIn("92", ans)
        # the stale record is quoted with its age, flagged as conflict
        self.assertIn("CONFLICT", ans)
        self.assertIn("as of 30h ago", ans)
        self.assertIn("15GiB", ans)

    def test_board_only_answer_is_freshness_tagged(self):
        out = host_status(
            "kk-mac", now=NOW, cards=[STALE_KK_CARD],
            board_only=True)
        self.assertEqual(out["confidence"], "board_only")
        self.assertFalse(out["contradiction"])
        ans = out["answer"]
        self.assertIn("stale-prone", ans)
        self.assertIn("as of", ans)          # freshness tag present
        self.assertIn("15GiB", ans)

    def test_no_telemetry_no_records(self):
        out = host_status("mn01", now=NOW, cards=[],
                          heartbeat_docs=[], nest_docs=[])
        self.assertEqual(out["confidence"], "board_only")
        self.assertIn("mn01", out["answer"])

    def test_nest_page_age(self):
        docs = [{"title": "nest-kk-mac", "slug": "nest-kks-mac-studio",
                 "meta": {"updated": [datetime.fromtimestamp(NOW - 600)
                                      .isoformat()]}}]
        nest = nest_page("kk-mac", cms_docs=docs, now=NOW)
        self.assertTrue(nest["found"])
        self.assertIn("10m", nest["page_age"])

    def test_nest_page_absent(self):
        nest = nest_page("kk-mac", cms_docs=[], now=NOW)
        self.assertFalse(nest["found"])


class HelperTest(unittest.TestCase):
    def test_age_str(self):
        self.assertEqual(age_str(30), "30s ago")
        self.assertEqual(age_str(240), "4m ago")
        self.assertEqual(age_str(22 * 3600), "22h ago")
        self.assertEqual(age_str(3 * 86400), "3d ago")
        self.assertEqual(age_str(None), "unknown age")

    def test_parse_ts(self):
        self.assertEqual(_parse_ts(123.0), 123.0)
        self.assertIsNotNone(_parse_ts("2026-11-09 18:36"))
        self.assertIsNotNone(_parse_ts("2026-11-09T18:36:00+07:00"))
        self.assertIsNone(_parse_ts("garbage"))
        self.assertIsNone(_parse_ts(None))


if __name__ == "__main__":
    unittest.main()
