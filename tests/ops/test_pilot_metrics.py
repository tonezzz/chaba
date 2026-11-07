"""Tests for pilot metrics (scripts/ops/pilot_metrics.py)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ops/pilot_metrics.py"

spec = importlib.util.spec_from_file_location("pilot_metrics", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["pilot_metrics"] = mod
spec.loader.exec_module(mod)


class PilotMetrics(unittest.TestCase):
    def test_free_lane_case(self):
        self.assertEqual(mod.cost_per_passed_gate(0.0, 1), 0.0)

    def test_paid_sample(self):
        self.assertAlmostEqual(mod.cost_per_passed_gate(0.30, 2), 0.15)

    def test_zero_gate_case(self):
        self.assertIsNone(mod.cost_per_passed_gate(0.0, 0))
        self.assertIsNone(mod.cost_per_passed_gate(0.30, -1))


if __name__ == "__main__":
    unittest.main()
