"""KNB-0036 regression: the runner claim loop must not write defer
comms to cards that are not in the claim queue.

Observed on lab-cf-kv-claw-channel.yml (column: done, action.status:
done): a stale action.runner=idc01 made the fleet-gap check report
'unclaimable by the declared runner fleet' on every pass. Every runner
then posted a fresh comms + awaiting_action note; 154+ notes grew the
card past the SSOT CI hard-bloat threshold.
"""

from __future__ import annotations

import importlib.util
import signal
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card(column: str, status: str = "done") -> dict:
    return {"id": "defer-card", "column": column,
            "title": "defer spam test",
            "action": {"type": "dispatch", "status": status,
                       "runner": "idc01"}}


class DoneCardDeferSpamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved_fn = {k: getattr(m, k) for k in (
            "api", "claimable", "_capacity_reason", "_claim_order",
            "self_stale_reason", "push_guard_reason",
            "executor_defer_reason", "dr_module", "note_defer")}
        self.cards = []
        self.posts = []
        self.defers = []

        m.api = lambda path, body=None: (
            self.posts.append((path, dict(body or {})))
            or ({"cards": self.cards} if path == "/cards" else {}))
        # Force every card into the defer branch; this test is about
        # whether a defer note is written, not claim eligibility.
        m.claimable = lambda card: ""
        m._capacity_reason = lambda st: ""
        m._claim_order = lambda cards: cards
        m.self_stale_reason = lambda: ""
        m.push_guard_reason = lambda card: ""
        m.executor_defer_reason = lambda card: ""
        m.dr_module = lambda: types.SimpleNamespace(
            unsatisfiable_reasons=lambda card, **kw: [
                "action.runner=idc01 names no declared runner"])
        m.note_defer = lambda card, kind, reason, **kw: \
            self.defers.append((card.get("id"), kind, reason, kw))
        signal.alarm(10)

    def tearDown(self):
        signal.alarm(0)
        for k, v in self._saved_fn.items():
            setattr(self.mod, k, v)

    def _comment_texts(self):
        return [b.get("text", "") for p, b in self.posts
                if p == "/comment"]

    def test_done_card_gets_no_defer_note(self):
        self.cards = [_card("done")]
        self.mod.claim_pass({})
        self.assertEqual(self.defers, [], self._comment_texts())
        self.assertEqual(self._comment_texts(), [])

    def test_review_card_gets_no_defer_note(self):
        self.cards = [_card("review")]
        self.mod.claim_pass({})
        self.assertEqual(self.defers, [])
        self.assertEqual(self._comment_texts(), [])

    def test_finished_action_in_backlog_gets_no_defer_note(self):
        # Both sides of the claim-state envelope matter: a stale queued
        # flag on a closed card is still off-queue.
        self.cards = [_card("backlog", status="done")]
        self.mod.claim_pass({})
        self.assertEqual(self.defers, [])
        self.assertEqual(self._comment_texts(), [])

    def test_queued_backlog_card_still_gets_unclaimable_note(self):
        # OPS-1097 must survive: a genuinely queued card no declared
        # runner can serve still reports why (incl. awaiting_action).
        self.cards = [_card("backlog", status="queued")]
        self.mod.claim_pass({})
        self.assertEqual(len(self.defers), 1, self._comment_texts())
        cid, kind, reason, kw = self.defers[0]
        self.assertEqual((cid, kind), ("defer-card", "unclaimable"))
        self.assertTrue(kw.get("awaiting"))
        self.assertIn("names no declared runner", reason)


class ClaimQueueColumnGateTest(unittest.TestCase):
    """KNB-0036 follow-through: the claim queue itself is column-scoped.

    PR #204 gated the defer-NOTES block, but _claimable() still returned
    a type for a done/review card carrying a stale action.status=queued
    (finish-less close-outs and do_move leave exactly that) — the claim
    POST stayed reachable, and _note_capacity_skip kept writing hostgate
    defer notes on the same off-queue cards. Both now gate on
    column in {backlog, doing} before any write."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved_fn = {k: getattr(m, k) for k in (
            "api", "note_defer")}
        self.cards = []
        self.posts = []
        self.defers = []
        m.api = lambda path, body=None: (
            self.posts.append((path, dict(body or {})))
            or ({"cards": self.cards} if path == "/cards" else {}))
        m.note_defer = lambda card, kind, reason, **kw: \
            self.defers.append((card.get("id"), kind, reason, kw))
        signal.alarm(10)

    def tearDown(self):
        signal.alarm(0)
        for k, v in self._saved_fn.items():
            setattr(self.mod, k, v)

    def _queued(self, column):
        return {"id": f"c-{column}", "column": column,
                "title": "t",
                "action": {"type": "dispatch", "status": "queued"}}

    def test_claimable_rejects_off_queue_columns(self):
        for col in ("done", "review", "lab"):
            typ, reason = self.mod._claimable(self._queued(col))
            self.assertEqual(typ, "", col)
            self.assertIn("claim queue", reason, col)

    def test_claimable_column_gate_comes_first(self):
        # an on-queue column passes the column gate and reaches the
        # status gate — proof the gate didn't swallow real cards
        typ, reason = self.mod._claimable(
            {"id": "c-b", "column": "backlog",
             "action": {"type": "dispatch", "status": "done"}})
        self.assertEqual((typ, reason), ("", "not queued"))
        # doing+queued gets PAST the column gate (deeper env-dependent
        # gates decide) — the reason is never the column refusal
        _typ, reason = self.mod._claimable(self._queued("doing"))
        self.assertNotIn("claim queue", reason)

    def test_capacity_skip_notes_only_on_queue_columns(self):
        # _note_capacity_skip writes hostgate defer comms during
        # capacity skips — it must honor the same column scope or the
        # spam just moves gate.
        self.cards = [self._queued(c) for c in
                      ("backlog", "doing", "review", "done")]
        self.mod._note_capacity_skip("host overloaded (test)")
        noted = {d[0] for d in self.defers}
        self.assertEqual(noted, {"c-backlog", "c-doing"})
        for _cid, kind, _reason, _kw in self.defers:
            self.assertEqual(kind, "hostgate")


if __name__ == "__main__":
    unittest.main()
