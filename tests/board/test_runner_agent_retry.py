"""Tests for runner-agent's per-card retry ledger
(dispatch-retry-storm-worktree-flood): consecutive claim failures back
off exponentially and a card at RETRY_MAX fails is held on this host
until a deliberate re-arm (attempts bump / human queue comms) — the
producer 're-spawned from report page' path must NOT forgive, or the
Nov 8-9 omen worktree flood (~130 in 36h) repeats.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"
sys.path.insert(0, str(REPO / "scripts" / "board"))


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent_retry",
                                                  SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card(cid="flood-card", comms=None, **action_kw):
    a = {"type": "dispatch", "status": "queued"}
    a.update(action_kw)
    return {"id": cid, "title": cid, "action": a,
            "comms": comms or []}


class RetryLedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self.m = m
        self._saved = {k: getattr(m, k) for k in (
            "RETRY_FILE", "RETRY_MAX", "RETRY_BASE_S", "RETRY_MAX_S",
            "STATE_DIR", "HOST")}
        self._tmpdir = tempfile.TemporaryDirectory()
        m.STATE_DIR = Path(self._tmpdir.name)
        m.RETRY_FILE = m.STATE_DIR / "retry-ledger.json"
        m.RETRY_MAX = 3
        m.RETRY_BASE_S = 1800
        m.RETRY_MAX_S = 21600
        m.HOST = "testhost"
        self.posts = []
        m.api = lambda path, body=None: (
            self.posts.append((path, body)) or {})

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.m, k, v)
        self._tmpdir.cleanup()

    def _ledger(self):
        return json.loads(self.m.RETRY_FILE.read_text())

    def test_no_entry_passes(self):
        self.assertEqual(self.m.retry_gate(_card()), "")

    def test_failure_backs_off(self):
        card = _card()
        self.m.retry_record_failure("flood-card", card)
        ent = self._ledger()["flood-card"]
        self.assertEqual(ent["fails"], 1)
        self.assertAlmostEqual(ent["next_ok"] - time.time(), 1800,
                               delta=30)
        reason = self.m.retry_gate(card)
        self.assertIn("backoff", reason)

    def test_backoff_is_exponential_and_capped(self):
        m = self.m
        card = _card()
        for _ in range(2):
            m.retry_record_failure("flood-card", card)
        ent = self._ledger()["flood-card"]
        self.assertEqual(ent["fails"], 2)
        self.assertAlmostEqual(ent["next_ok"] - time.time(), 3600,
                               delta=30)
        # fails=3 hits RETRY_MAX -> held, not merely backed off
        m.retry_record_failure("flood-card", card)
        reason = m.retry_gate(card)
        self.assertIn("retry cap", reason)

    def test_cap_posts_awaiting_note(self):
        card = _card()
        for _ in range(3):
            self.m.retry_record_failure("flood-card", card)
        caps = [b for p, b in self.posts if p == "/comment"
                and (b or {}).get("awaiting_action")]
        self.assertTrue(caps)
        self.assertIn("retry cap", caps[-1]["text"])

    def test_backoff_expiry_allows_claim(self):
        m = self.m
        card = _card()
        m.retry_record_failure("flood-card", card)
        ent = self._ledger()["flood-card"]
        ent["next_ok"] = int(time.time()) - 1  # expired
        m.RETRY_FILE.write_text(json.dumps(self._ledger()
                                           | {"flood-card": ent}))
        self.assertEqual(m.retry_gate(card), "")

    def test_producer_respawn_does_not_forgive(self):
        """The flood driver: re-spawned-from-report-page comms must
        NOT reset the ledger."""
        m = self.m
        card = _card(comms=[
            {"at": "2026-11-17 18:00", "from": "devin",
             "text": "re-spawned from report page"}])
        m.retry_record_failure("flood-card", card)
        for _ in range(2):
            m.retry_record_failure("flood-card", card)
        # card re-armed again by the producer — still capped
        card["comms"].append(
            {"at": "2026-11-17 18:30", "from": "devin",
             "text": "re-spawned from report page"})
        self.assertIn("retry cap", m.retry_gate(card))

    def test_manual_retry_forgives(self):
        """The ↺ retry verb's 'retry requested' comms -> fresh slate."""
        m = self.m
        card = _card()
        for _ in range(3):
            m.retry_record_failure("flood-card", card)
        self.assertIn("retry cap", m.retry_gate(card))
        card["action"]["attempts"] = 1
        card["comms"].append(
            {"at": "2026-11-17 19:00", "from": "tony",
             "text": "retry requested"})
        self.assertEqual(m.retry_gate(card), "")
        self.assertNotIn("flood-card", self._ledger())

    def test_attempts_alone_does_not_forgive(self):
        """kanban-dispatch's mark_start bumps attempts too — an
        interleaving sibling claim must not reset this host's ledger
        or the flood ping-pongs between dispatchers."""
        m = self.m
        card = _card()
        for _ in range(3):
            m.retry_record_failure("flood-card", card)
        card["action"]["attempts"] = 1  # sibling dispatcher claimed it
        self.assertIn("retry cap", m.retry_gate(card))

    def test_queue_verb_comms_forgives(self):
        """A human 'queued for processing' re-arm counts even without
        an attempts bump — but only ones NEWER than the failure
        baseline."""
        m = self.m
        card = _card(comms=[
            {"at": "2026-11-17 10:00", "from": "tony",
             "text": "queued for processing"}])  # pre-failure queue
        m.retry_record_failure("flood-card", card)
        # old queue comms is baseline, not a re-arm
        self.assertIn("backoff", m.retry_gate(card))
        # a NEW queue comms after the failure is a deliberate re-arm
        card["comms"].append(
            {"at": "2026-11-17 19:00", "from": "tony",
             "text": "queued for processing"})
        self.assertEqual(m.retry_gate(card), "")

    def test_success_clears_ledger(self):
        m = self.m
        m.retry_record_failure("flood-card", _card())
        m.retry_record_success("flood-card")
        self.assertNotIn("flood-card", self._ledger())

    def test_gate_disabled_at_zero(self):
        m = self.m
        m.RETRY_MAX = 0
        card = _card()
        m.retry_record_failure("flood-card", card)
        self.assertFalse(m.RETRY_FILE.exists())
        self.assertEqual(m.retry_gate(card), "")

    def test_missing_baseline_does_not_forgive(self):
        """An entry recorded before the card was visible must not let
        an OLD 'queued for processing' comms count as a re-arm."""
        m = self.m
        m.retry_record_failure("flood-card")          # no card -> no baseline
        card = _card(comms=[
            {"at": "2026-11-17 10:00", "from": "tony",
             "text": "queued for processing"}])
        self.assertIn("backoff", m.retry_gate(card))
        # a fresh re-arm after the baseline is established forgives
        ent = self._ledger()["flood-card"]
        ent["next_ok"] = int(time.time()) - 1
        m.RETRY_FILE.write_text(
            json.dumps({"flood-card": ent}))
        m.retry_gate(card)  # establishes baseline now
        card["comms"].append(
            {"at": "2026-11-17 19:30", "from": "tony",
             "text": "retry requested"})
        self.assertEqual(m.retry_gate(card), "")


class ClaimPassGateTest(unittest.TestCase):
    """claim_pass must skip a held card before any claim POST."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self.m = m
        self._saved = {k: getattr(m, k) for k in (
            "RETRY_FILE", "RETRY_MAX", "STATE_DIR", "HOST", "CAP",
            "WAITING_GATE", "MAX_LOAD_PC")}
        self._tmpdir = tempfile.TemporaryDirectory()
        m.STATE_DIR = Path(self._tmpdir.name)
        m.RETRY_FILE = m.STATE_DIR / "retry-ledger.json"
        m.RETRY_MAX = 3
        m.HOST = "testhost"
        m.CAP = 2
        m.WAITING_GATE = "off"
        m.MAX_LOAD_PC = 0      # 0 disables the load gate — never overloaded
        self.claims = []
        self._cards = []
        m.api = lambda path, body=None: (
            self.claims.append((path, body)) or
            ({"cards": self._cards} if path == "/cards" and body is None
             else {}))
        m.claimable = lambda card: "dispatch"
        m.push_guard_reason = lambda card: ""
        m.executor_defer_reason = lambda card: ""
        m.self_stale_reason = lambda: ""
        m.gpu_preflight = lambda card: ""
        m.dr_module = lambda: None
        m.start_task = lambda card, typ: ("devin-task-x-1", "x-1", "")
        m._note_capacity_skip = lambda cap, exempt=None: None

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.m, k, v)
        self._tmpdir.cleanup()

    def _claim_posts(self):
        return [b for p, b in self.claims
                if p == "/action" and (b or {}).get("do") == "claim"]

    def test_held_card_never_claims(self):
        m = self.m
        card = _card()
        for _ in range(3):
            m.retry_record_failure("flood-card", card)
        self._cards = [card]
        st = {}
        m.claim_pass(st)
        self.assertEqual(self._claim_posts(), [])
        self.assertEqual(st, {})

    def test_backed_off_card_never_claims(self):
        m = self.m
        card = _card()
        m.retry_record_failure("flood-card", card)
        self._cards = [card]
        st = {}
        m.claim_pass(st)
        self.assertEqual(self._claim_posts(), [])

    def test_start_failure_records_ledger(self):
        m = self.m
        m.start_task = lambda card, typ: ("", "", "boom")
        self._cards = [_card()]
        m.claim_pass({})
        self.assertIn("flood-card", json.loads(
            m.RETRY_FILE.read_text()))

    def test_forgiven_card_claims(self):
        m = self.m
        card = _card()
        m.retry_record_failure("flood-card", card)
        card["comms"].append(           # human retry verb
            {"at": "2026-11-17 19:00", "from": "tony",
             "text": "retry requested"})
        self._cards = [card]
        st = {}
        m.claim_pass(st)
        self.assertEqual(len(self._claim_posts()), 1)
        self.assertIn("flood-card", st)


if __name__ == "__main__":
    unittest.main()
