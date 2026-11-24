"""Tests for the lane-routing watch block in scripts/board/kanban-stats.py
(card devin-lane-cheap-ops-reroute / DEV-0045 — "watch misroute rate").

The block buckets stamped action.lane on OPEN cards by lane_source
provenance so classifier misroute cohorts stay visible on the 15m
kanban-stats report.
"""

import datetime
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "kanban_stats", REPO / "scripts" / "board" / "kanban-stats.py")
ks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ks)

NOW = datetime.datetime(2026, 11, 24, 12, 0,
                        tzinfo=ks.BANGKOK)


def _card(cid, column="backlog", action=None):
    c = {"id": cid, "column": column, "title": cid,
         "updated": "2026-11-24 10:00"}
    if action is not None:
        c["action"] = action
    return c


class LaneRoutingCollectTest(unittest.TestCase):
    def test_pin_vs_classifier_sources(self):
        cards = [
            _card("pin-devin", action={"lane": "devin"}),
            _card("kw-free", action={"lane": "free_lane",
                                     "lane_source": "kw"}),
            _card("claim-devin", action={"lane": "devin",
                                         "lane_source": "claim"}),
            _card("fb-devin", action={"lane": "devin",
                                      "lane_source": "fallback"}),
        ]
        stats = ks.collect(cards, NOW)
        lr = stats["lane_routing"]
        self.assertEqual(lr["stamped"], 4)
        self.assertEqual(lr["cells"]["devin"],
                         {"pin": 1, "claim": 1, "fallback": 1})
        self.assertEqual(lr["cells"]["free_lane"], {"kw": 1})

    def test_done_column_excluded_unstamped_dispatch_counted(self):
        cards = [
            _card("done-lane", column="done",
                  action={"lane": "devin", "status": "done"}),
            _card("open-dispatch", action={"type": "dispatch"}),
            _card("open-script", action={"type": "script"}),
            _card("no-action"),
        ]
        stats = ks.collect(cards, NOW)
        lr = stats["lane_routing"]
        self.assertEqual(lr["stamped"], 0)
        self.assertEqual(lr["unstamped_dispatch"], 1)

    def test_scalar_action_does_not_break(self):
        # marker cards carry action as a scalar — _act must not stamp
        cards = [_card("marker", action="spec-review")]
        stats = ks.collect(cards, NOW)
        self.assertEqual(stats["lane_routing"]["stamped"], 0)


class LaneRoutingRenderTest(unittest.TestCase):
    def test_render_matrix_and_note(self):
        stats = ks.collect(
            [_card("a", action={"lane": "devin"}),
             _card("b", action={"lane": "free_lane",
                                "lane_source": "kw"})], NOW)
        md = ks.render_md(stats)
        self.assertIn("## Lane routing", md)
        self.assertIn("| lane |", md)
        self.assertIn("| devin |", md)
        self.assertIn("| free_lane |", md)
        self.assertIn("pin", md)
        self.assertIn("re-evaluate on re-queue", md)

    def test_render_empty_state(self):
        stats = ks.collect([_card("x")], NOW)
        md = ks.render_md(stats)
        self.assertIn("no stamped `action.lane`", md)


if __name__ == "__main__":
    unittest.main()
