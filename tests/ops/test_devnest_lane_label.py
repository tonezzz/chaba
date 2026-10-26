"""Tests for the DevNest lane classifier (scripts/ops/devnest_lane_label.py)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ops/devnest_lane_label.py"

spec = importlib.util.spec_from_file_location("devnest_lane_label", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["devnest_lane_label"] = mod
spec.loader.exec_module(mod)


class LaneLabel(unittest.TestCase):
    def test_purge_routes_to_codemod(self):
        self.assertEqual(
            mod.lane_label("purge stale kanban heartbeat files"), "codemod")

    def test_config_routes_to_codemod(self):
        self.assertEqual(
            mod.lane_label("bump the config version in ssot"), "codemod")

    def test_physical_routes_to_manual(self):
        self.assertEqual(
            mod.lane_label("physical reseat of the omen NVMe stick"),
            "manual")

    def test_hardware_routes_to_manual(self):
        self.assertEqual(
            mod.lane_label("order replacement hardware for kk-macbook"),
            "manual")

    def test_default_routes_to_devin(self):
        self.assertEqual(
            mod.lane_label("investigate why the nest queue stalled"),
            "devin")

    def test_empty_text_routes_to_devin(self):
        self.assertEqual(mod.lane_label(""), "devin")


if __name__ == "__main__":
    unittest.main()
