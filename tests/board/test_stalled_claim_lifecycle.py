"""Stalled-claim lifecycle tests (card
dispatch-failed-cards-park-in-doing).

The lifecycle rule: 'doing' means a live claim exists.

  (a) a failed/dead claim leaves doing — board-api do_finish and
      kanban-dispatch's fail paths requeue under the attempts cap,
      else park the card failed in backlog
  (b) merge-sweep's stalled-claim reaper flags doing+running cards
      with no live unit/runner report older than the stall horizon,
      and moves provably-dead statuses to the honest column
  (c) claims set doing from any non-terminal column and stamp
      claim.since; /action do=retry resets attempts (human re-arm)
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "board" / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BoardApiLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load("stalled_api", "board-api.py")

    def card(self, **kw):
        c = {"id": "lc-card", "column": "doing", "comms": [],
             "action": {"type": "dispatch", "status": "running",
                        "runner": "idc02", "task_id": "t-1"}}
        c.update(kw)
        return c

    # -- do_finish failure path -------------------------------------
    def test_finish_fail_under_cap_requeues_to_backlog(self):
        c = self.card()
        c["action"]["attempts"] = 1
        msg = self.api.do_finish(c, {"host": "idc02", "ok": False,
                                     "result": "unit died"})
        a = c["action"]
        self.assertEqual(a["status"], "queued")
        self.assertEqual(c["column"], "backlog")
        self.assertNotIn("runner", a)
        self.assertNotIn("task_id", a)
        self.assertEqual(a.get("last_failure"), "unit died")
        self.assertIn("auto-retry queued", msg)
        self.assertTrue(any("auto-retry queued" in m["text"]
                            for m in c["comms"]))

    def test_finish_fail_at_cap_parks_failed_in_backlog(self):
        c = self.card()
        c["action"]["attempts"] = 2
        msg = self.api.do_finish(c, {"host": "idc02", "ok": False,
                                     "result": "died again"})
        a = c["action"]
        self.assertEqual(a["status"], "failed")
        self.assertEqual(c["column"], "backlog")
        self.assertEqual(msg, "marked failed")
        self.assertTrue(any("attempt cap" in m["text"]
                            for m in c["comms"]))

    def test_finish_fail_autoretry_off_parks(self):
        with unittest.mock.patch.dict(
                os.environ, {"KANBAN_AUTORETRY": "0"}):
            c = self.card()
            c["action"]["attempts"] = 0
            self.api.do_finish(c, {"host": "idc02", "ok": False,
                                   "result": "died"})
            self.assertEqual(c["action"]["status"], "failed")
            self.assertEqual(c["column"], "backlog")

    def test_finish_fail_lane_envelope_zero_retries_parks(self):
        # ADA-0242 contract: a typed lane_envelope may tighten the retry
        # budget — escalation.max_retries:0 means one dispatch total,
        # so a failed finish parks instead of auto-requeueing attempt 2.
        c = self.card()
        c["action"]["attempts"] = 1
        c["action"]["lane_envelope"] = {
            "escalation": {"on_fail": "manual", "max_retries": 0}}
        msg = self.api.do_finish(c, {"host": "idc02", "ok": False,
                                     "result": "provider 429"})
        a = c["action"]
        self.assertEqual(a["status"], "failed")
        self.assertEqual(c["column"], "backlog")
        self.assertEqual(msg, "marked failed")
        self.assertEqual(a.get("last_failure"), "provider 429")
        self.assertTrue(any("attempt cap 1" in m["text"]
                            for m in c["comms"]))

    def test_finish_ok_still_goes_review(self):
        c = self.card()
        self.api.do_finish(c, {"host": "idc02", "ok": True})
        self.assertEqual(c["action"]["status"], "done")
        self.assertEqual(c["column"], "review")

    # -- do_claim -----------------------------------------------------
    def test_claim_bumps_attempts_and_stamps_since(self):
        c = {"id": "lc-claim", "column": "backlog", "comms": [],
             "action": {"type": "dispatch", "status": "queued"}}
        self.api.do_claim(c, {"host": "tony-omen"})
        self.assertEqual(c["action"]["attempts"], 1)
        self.assertEqual(c["column"], "doing")
        self.assertTrue((c.get("claim") or {}).get("since"))

    def test_claim_from_review_moves_doing(self):
        c = {"id": "lc-claim2", "column": "review", "comms": [],
             "action": {"type": "dispatch", "status": "queued"}}
        self.api.do_claim(c, {"host": "mn01"})
        self.assertEqual(c["column"], "doing")

    def test_claim_refused_at_attempt_cap(self):
        c = {"id": "lc-cap", "column": "backlog", "comms": [],
             "action": {"type": "dispatch", "status": "queued",
                        "attempts": 2}}
        try:
            self.api.do_claim(c, {"host": "mn01"})
        except ValueError as e:
            self.assertIn("attempt cap", str(e))
            return
        raise AssertionError("claim at cap should be refused")

    def test_claim_refused_at_lane_envelope_cap(self):
        c = {"id": "lc-env-cap", "column": "backlog", "comms": [],
             "action": {"type": "dispatch", "status": "queued",
                        "attempts": 1,
                        "lane_envelope": {"escalation":
                                          {"max_retries": 0}}}}
        try:
            self.api.do_claim(c, {"host": "mn01"})
        except ValueError as e:
            self.assertIn("attempt cap reached (1/1)", str(e))
            return
        raise AssertionError("claim at lane-envelope cap should be refused")

    # -- claim lane provenance (devin-lane-cheap-ops-reroute) ---------
    def _queued(self, cid, **action):
        a = {"type": "dispatch", "status": "queued"}
        a.update(action)
        return {"id": cid, "column": "backlog", "comms": [],
                "action": a}

    def test_claim_lane_stamp_gets_lane_source(self):
        # A claim-time lane is classifier output — it must persist
        # lane_source so the next queue re-evaluates it. A bare stamp
        # reads as an author pin forever (the audit's explicit bucket).
        c = self._queued("lc-lane-stamp")
        self.api.do_claim(c, {"host": "mn01", "lane": "free_lane",
                              "model": "litellm/gemini-3.5-flash-lite"})
        self.assertEqual(c["action"]["lane"], "free_lane")
        self.assertEqual(c["action"]["lane_source"], "claim")

    def test_claim_lane_source_from_body_wins(self):
        c = self._queued("lc-lane-src")
        self.api.do_claim(c, {"host": "mn01", "lane": "devin",
                              "lane_source": "kw"})
        self.assertEqual(c["action"]["lane_source"], "kw")

    def test_claim_preserves_existing_lane_source(self):
        # Queue-time classify already stamped provenance — a bare claim
        # lane must not downgrade it to the generic 'claim' marker.
        c = self._queued("lc-lane-keep", lane="devin",
                         lane_source="kw")
        self.api.do_claim(c, {"host": "mn01", "lane": "devin"})
        self.assertEqual(c["action"]["lane_source"], "kw")

    def test_claim_never_provenances_author_pin(self):
        # An author-set lane (no lane_source on the card) is explicit
        # routing — even a claim carrying lane_source must not stamp it.
        c = self._queued("lc-lane-pin", lane="devin")
        self.api.do_claim(c, {"host": "mn01", "lane": "devin",
                              "lane_source": "claim"})
        self.assertEqual(c["action"]["lane"], "devin")
        self.assertNotIn("lane_source", c["action"])

    # -- verbs --------------------------------------------------------
    def test_retry_resets_attempts_and_column(self):
        c = {"id": "lc-retry", "column": "doing", "comms": [],
             "action": {"type": "dispatch", "status": "failed",
                        "attempts": 3, "runner": "mn01",
                        "task_id": "t-9", "result": "died"},
             "claim": {"session": "t-9"}}
        self.api.do_action(c, "retry", "tony")
        a = c["action"]
        self.assertEqual(a["status"], "queued")
        self.assertEqual(a["attempts"], 0)
        self.assertNotIn("runner", a)
        self.assertNotIn("task_id", a)
        self.assertEqual(c["column"], "backlog")
        self.assertEqual(a.get("last_failure"), "died")

    def test_queue_from_doing_goes_backlog(self):
        c = {"id": "lc-q", "column": "doing", "comms": [],
             "action": {"type": "dispatch", "status": "failed"}}
        self.api.do_action(c, "queue", "tony")
        self.assertEqual(c["action"]["status"], "queued")
        self.assertEqual(c["column"], "backlog")


class DispatchLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kd = _load("stalled_kd", "kanban-dispatch.py")

    def test_mark_start_sets_doing_and_since(self):
        card = {"id": "lc-ms", "column": "backlog", "comms": [],
                "action": {"status": "queued"}}
        self.kd.mark_start(Path("/tmp/x"), card)
        self.assertEqual(card["column"], "doing")
        self.assertEqual(card["action"]["status"], "starting")
        self.assertEqual(card["action"]["attempts"], 1)
        self.assertTrue((card.get("claim") or {}).get("since"))

    def test_fail_or_requeue_under_cap(self):
        card = {"id": "lc-f", "column": "doing", "comms": [],
                "action": {"status": "running", "attempts": 1,
                           "runner": "tony-dell", "task_id": "t-1"},
                "claim": {"session": "t-1"}}
        verdict = self.kd._fail_or_requeue(card, "unit died")
        a = card["action"]
        self.assertEqual(a["status"], "queued")
        self.assertEqual(card["column"], "backlog")
        self.assertNotIn("runner", a)
        self.assertNotIn("session", card.get("claim") or {})
        self.assertIn("auto-retry queued", verdict)

    def test_fail_or_requeue_at_cap(self):
        card = {"id": "lc-f2", "column": "doing", "comms": [],
                "action": {"status": "running", "attempts": 2}}
        verdict = self.kd._fail_or_requeue(card, "unit died")
        self.assertEqual(card["action"]["status"], "failed")
        self.assertEqual(card["column"], "backlog")
        self.assertIn("attempt cap", verdict)

    def test_fail_or_requeue_lane_envelope_zero_retries(self):
        card = {"id": "lc-f-env", "column": "doing", "comms": [],
                "action": {"status": "running", "attempts": 1,
                           "runner": "idc02", "task_id": "t-env",
                           "lane_envelope": {"escalation":
                                             {"max_retries": 0}}},
                "claim": {"session": "t-env"}}
        verdict = self.kd._fail_or_requeue(card, "provider 429")
        a = card["action"]
        self.assertEqual(a["status"], "failed")
        self.assertEqual(card["column"], "backlog")
        self.assertEqual(a.get("last_failure"), "provider 429")
        self.assertIn("attempt cap 1", verdict)
        self.assertNotIn("session", card.get("claim") or {})

    def test_finish_one_failed_unit_requeues(self):
        # probe = (task_id, unit_state, ex_ok, ex_ev, sess_probe)
        card = {"id": "lc-fo", "column": "doing", "comms": [],
                "action": {"status": "running", "attempts": 1,
                           "task_id": "t-x", "runner":
                           self.kd.HOST}}
        msg = self.kd.finish_one(
            Path("/tmp/lc-fo.yml"), card,
            probe=("t-x", "failed", None, None, None))
        self.assertEqual(msg, "failed")
        self.assertEqual(card["action"]["status"], "queued")
        self.assertEqual(card["column"], "backlog")


class AttemptCapTest(unittest.TestCase):
    """dispatch_repos.dispatch_attempt_cap — the shared cap used by
    board-api, kanban-dispatch, and merge-sweep."""

    @classmethod
    def setUpClass(cls):
        cls.dr = _load("stalled_dr", "dispatch_repos.py")

    def cap(self, action):
        return self.dr.dispatch_attempt_cap({"action": action})

    def test_default_cap_is_two(self):
        self.assertEqual(self.cap({"type": "dispatch"}), 2)

    def test_max_attempts_override(self):
        self.assertEqual(self.cap({"type": "dispatch",
                                   "max_attempts": 4}), 4)

    def test_envelope_zero_retries_caps_at_one(self):
        self.assertEqual(self.cap({
            "type": "dispatch",
            "lane_envelope": {"escalation": {"max_retries": 0}}}), 1)

    def test_envelope_retries_tighten_generic_cap(self):
        # max_retries counts retries AFTER the first dispatch: 1 retry
        # under a generic cap of 4 still means two total dispatches.
        self.assertEqual(self.cap({
            "type": "dispatch", "max_attempts": 4,
            "lane_envelope": {"escalation": {"max_retries": 1}}}), 2)

    def test_envelope_cannot_widen_generic_cap(self):
        self.assertEqual(self.cap({
            "type": "dispatch", "max_attempts": 1,
            "lane_envelope": {"escalation": {"max_retries": 5}}}), 1)

    def test_envelope_without_max_retries_keeps_generic_cap(self):
        self.assertEqual(self.cap({
            "type": "dispatch", "max_attempts": 3,
            "lane_envelope": {"escalation": {"on_fail": "manual"}}}), 3)

    def test_invalid_max_retries_fails_closed(self):
        self.assertEqual(self.cap({
            "type": "dispatch", "max_attempts": 3,
            "lane_envelope": {"escalation": {"max_retries": "x"}}}), 1)


class ReaperTest(unittest.TestCase):
    """merge-sweep.reap_stalled_claims — the periodic honesty lane."""

    @classmethod
    def setUpClass(cls):
        cls.ms = _load("stalled_ms", "merge-sweep.py")

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._card_dir = self.ms.CARD_DIR
        self._api = self.ms.API
        self.ms.CARD_DIR = self.tmp / "cards"
        self.ms.CARD_DIR.mkdir()
        self.ms.API = "http://127.0.0.1:9"  # dead — live_claim_ids=None

    def tearDown(self):
        self.ms.CARD_DIR = self._card_dir
        self.ms.API = self._api
        self._td.cleanup()

    def write_card(self, card: dict) -> dict:
        card.setdefault("id", "lc-reap")
        card.setdefault("comms", [])
        (self.ms.CARD_DIR / f"{card['id']}.yml").write_text(
            yaml.safe_dump(card, sort_keys=False))
        return card

    def read_card(self, cid: str = "lc-reap") -> dict:
        return yaml.safe_load(
            (self.ms.CARD_DIR / f"{cid}.yml").read_text())

    OLD = "2020-01-01 00:00"

    def reap(self, cards, active=None, live=None):
        return self.ms.reap_stalled_claims(cards, active or {},
                                           live, dry=False)

    def test_failed_doing_moves_backlog(self):
        c = self.write_card({"column": "doing",
                             "action": {"type": "dispatch",
                                        "status": "failed"},
                             "updated": self.OLD})
        self.assertTrue(self.reap([c]))
        c = self.read_card()
        self.assertEqual(c["column"], "backlog")
        self.assertTrue(any("stalled-claim reaper" in m["text"]
                            for m in c["comms"]))

    def test_done_doing_moves_review(self):
        c = self.write_card({"column": "doing",
                             "action": {"type": "dispatch",
                                        "status": "done"},
                             "updated": self.OLD})
        self.assertTrue(self.reap([c]))
        self.assertEqual(self.read_card()["column"], "review")

    def test_queued_doing_moves_backlog(self):
        c = self.write_card({"column": "doing",
                             "action": {"type": "dispatch",
                                        "status": "queued"},
                             "updated": self.OLD})
        self.assertTrue(self.reap([c]))
        self.assertEqual(self.read_card()["column"], "backlog")

    def test_running_dead_claim_flagged_not_moved(self):
        c = self.write_card({
            "column": "doing",
            "action": {"type": "dispatch", "status": "running",
                       "runner": "idc02", "task_id": "t-dead"},
            "claim": {"since": self.OLD},
            "updated": self.OLD})
        self.assertTrue(self.reap([c]))  # live_ids None, no unit
        c = self.read_card()
        self.assertEqual(c["column"], "doing")  # flag, never move
        self.assertTrue(c.get("awaiting_action"))
        self.assertTrue((c["action"].get("sweep") or {})
                        .get("stalled_claim"))

    def test_running_live_unit_untouched(self):
        c = self.write_card({
            "column": "doing",
            "action": {"type": "dispatch", "status": "running",
                       "runner": "idc02", "task_id": "t-live"},
            "claim": {"since": self.OLD},
            "updated": self.OLD})
        self.assertFalse(self.reap([c], active={"t-live": {"host": "idc02"}}))
        self.assertEqual(self.read_card()["column"], "doing")
        self.assertFalse(self.read_card().get("awaiting_action"))

    def test_running_fresh_heartbeat_untouched(self):
        c = self.write_card({
            "column": "doing",
            "action": {"type": "dispatch", "status": "running",
                       "runner": "idc02", "task_id": "t-remote"},
            "claim": {"since": self.OLD},
            "updated": self.OLD})
        self.assertFalse(self.reap([c], live={"lc-reap"}))
        self.assertEqual(self.read_card()["column"], "doing")

    def test_running_young_claim_untouched(self):
        from datetime import datetime
        recent = datetime.now().strftime("%Y-%m-%d %H:%M")
        c = self.write_card({
            "column": "doing",
            "action": {"type": "dispatch", "status": "running",
                       "runner": "idc02", "task_id": "t-young"},
            "claim": {"since": recent},
            "updated": recent})
        self.assertFalse(self.reap([c]))
        c = self.read_card()
        self.assertEqual(c["column"], "doing")
        self.assertFalse(c.get("awaiting_action"))

    def test_orphan_doing_old_flags_then_moves_backlog(self):
        # first sighting: flag, not move — could be real offline work
        c = self.write_card({"column": "doing", "updated": self.OLD})
        self.assertTrue(self.reap([c]))
        c = self.read_card()
        self.assertEqual(c["column"], "doing")
        self.assertTrue(c.get("awaiting_action"))
        self.assertTrue(((c.get("action") or {}).get("sweep") or {})
                        .get("stalled_claim"))
        # still untouched a pass later (the real sweep re-reads cards
        # each run — pass the fresh copy): honest column wins
        self.assertTrue(self.reap([self.read_card()]))
        self.assertEqual(self.read_card()["column"], "backlog")

    def test_orphan_doing_fresh_untouched(self):
        from datetime import datetime
        recent = datetime.now().strftime("%Y-%m-%d %H:%M")
        c = self.write_card({"column": "doing", "updated": recent})
        self.assertFalse(self.reap([c]))
        self.assertEqual(self.read_card()["column"], "doing")

    def test_terminal_and_other_columns_untouched(self):
        c = self.write_card({"column": "done",
                             "action": {"status": "failed"},
                             "updated": self.OLD})
        self.assertFalse(self.reap([c]))
        self.assertEqual(self.read_card()["column"], "done")


if __name__ == "__main__":
    import unittest.mock  # noqa: F401  (used in patch.dict above)
    unittest.main()
