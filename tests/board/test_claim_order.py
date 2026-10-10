"""Unit tests for the shared priority claim order (card
dispatch-priority-order): dispatch_repos.claim_sort_key drives both
kanban-dispatch's local drain and runner-agent's remote claim.

Covers the card's acceptance: a [low old, high new, normal oldest]
queue drains high -> normal -> low; a 13h-old low card beats a fresh
high (starvation guard); labels/caps still gate eligibility (tested via
runner-agent claim_pass integration — ordering never bypasses
claimable()).
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
import dispatch_repos as dr  # noqa: E402

RUNNER = REPO / "scripts/board/runner-agent.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("runner_agent", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ago(hours: float) -> str:
    """card `updated` string `hours` in the past (the +07 convention)."""
    return (datetime.now(dr.CARD_TZ) - timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M")


def card(cid: str, priority: str | None = None,
         updated_hours: float = 1.0, **action) -> dict:
    c = {"id": cid, "updated": ago(updated_hours)}
    if priority is not None:
        c["priority"] = priority
    if action:
        c["action"] = action
    return c


def order(cards: list, starve_hours: float = 12.0) -> list:
    return [c["id"] for c in dr.sort_claimable(
        cards, starve_hours=starve_hours)]


class ClaimSortKeyTest(unittest.TestCase):
    def test_acceptance_mixed_queue_drains_high_normal_low(self):
        """[low old, high new, normal oldest] -> high, normal, low —
        absent-priority ('normal') ranks between medium and low, same as
        the board's next-up column order."""
        q = [card("low-old", "low", updated_hours=3),
             card("high-new", "high", updated_hours=0.1),
             card("normal-oldest", updated_hours=6)]  # absent priority
        self.assertEqual(order(q),
                         ["high-new", "normal-oldest", "low-old"])

    def test_full_rank_order(self):
        q = [card("p-low", "low"),
             card("p-absent"),
             card("p-medium", "medium"),
             card("p-high", "high")]
        self.assertEqual(order(q),
                         ["p-high", "p-medium", "p-absent", "p-low"])

    def test_same_priority_oldest_first(self):
        q = [card("newer", "medium", updated_hours=1),
             card("older", "medium", updated_hours=5),
             card("mid", "medium", updated_hours=3)]
        self.assertEqual(order(q), ["older", "mid", "newer"])

    def test_starving_low_beats_fresh_high(self):
        """13h-old low card claims ahead of a fresh high — priority is a
        bias, not a ban."""
        q = [card("high-fresh", "high", updated_hours=0.1),
             card("low-13h", "low", updated_hours=13)]
        self.assertEqual(order(q), ["low-13h", "high-fresh"])

    def test_starvation_boundary_and_disable(self):
        old_low = card("low-old", "low", updated_hours=13)
        fresh_high = card("high-new", "high", updated_hours=0.1)
        # inside the window the high still wins
        not_yet = card("low-11h", "low", updated_hours=11)
        self.assertEqual(order([fresh_high, not_yet]),
                         ["high-new", "low-11h"])
        # starve_hours=0 disables the tier entirely
        self.assertEqual(order([old_low, fresh_high], starve_hours=0),
                         ["high-new", "low-old"])

    def test_starved_high_still_beats_starved_low(self):
        q = [card("low-20h", "low", updated_hours=20),
             card("high-13h", "high", updated_hours=13)]
        self.assertEqual(order(q), ["high-13h", "low-20h"])

    def test_unreadable_updated_never_starves(self):
        """A card that can't prove its age wins its rank's tie-break but
        doesn't take the starvation tier."""
        q = [card("high-fresh", "high", updated_hours=0.1),
             {"id": "low-nodate", "priority": "low"}]  # no updated
        self.assertEqual(order(q), ["high-fresh", "low-nodate"])
        # ...but it does sort oldest within its own rank
        q2 = [card("low-1h", "low", updated_hours=1),
              {"id": "low-nodate", "priority": "low"}]
        self.assertEqual(order(q2), ["low-nodate", "low-1h"])

    def test_stable_within_identical_keys(self):
        stamp = ago(1)
        q = [{"id": "b", "updated": stamp},
             {"id": "a", "updated": stamp}]
        self.assertEqual(order(q), ["b", "a"])


class RunnerAgentClaimOrderTest(unittest.TestCase):
    """claim_pass drains /cards in the shared order and only through the
    normal gates (claimable / blocked_by / gpu preflight still apply)."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_runner()

    def setUp(self):
        m = self.mod
        self.claimed = []
        self._saved = (m.api, m.claimable, m.start_task, m.gpu_preflight,
                       m.CAP, m.STARVE_HOURS)
        m.CAP = 10
        m.STARVE_HOURS = 12
        self.cards = []
        m.api = lambda path, body=None: (
            {"cards": self.cards} if path == "/cards"
            else (self.claimed.append(body.get("id"))
                  if path == "/action" and body.get("do") == "claim"
                  else None) or {})
        m.claimable = lambda c: (
            "script" if (c.get("action") or {}).get("status") == "queued"
            else "")
        m.gpu_preflight = lambda c: ""
        m.start_task = lambda c, t: (f"u-{c['id']}", "", "")

    def tearDown(self):
        (self.mod.api, self.mod.claimable, self.mod.start_task,
         self.mod.gpu_preflight, self.mod.CAP,
         self.mod.STARVE_HOURS) = self._saved

    def test_claims_drain_in_priority_order(self):
        self.cards = [
            card("low-old", "low", 3, status="queued"),
            card("high-new", "high", 0.1, status="queued"),
            card("normal-oldest", None, 6, status="queued"),
            card("not-queued", "high", 0.1, status="running"),
        ]
        self.mod.claim_pass({})
        self.assertEqual(self.claimed,
                         ["high-new", "normal-oldest", "low-old"])

    def test_starving_card_claims_first(self):
        self.cards = [
            card("high-fresh", "high", 0.1, status="queued"),
            card("low-13h", "low", 13, status="queued"),
        ]
        self.mod.claim_pass({})
        self.assertEqual(self.claimed, ["low-13h", "high-fresh"])

    def test_ineligible_cards_keep_gating(self):
        """Ordering never bypasses claimable() — a high card this host
        can't run stays unclaimed while a lower eligible one drains."""
        self.cards = [
            card("gpu-high", "high", 0.1, status="queued"),
            card("low-ok", "low", 0.1, status="queued"),
        ]
        self.mod.claimable = lambda c: (
            "" if c["id"] == "gpu-high" else "script")
        self.mod.claim_pass({})
        self.assertEqual(self.claimed, ["low-ok"])


if __name__ == "__main__":
    unittest.main()
