#!/usr/bin/env python3
"""pilot-metrics — pure cost and gate efficiency functions for DevNest pilots.

Pure function: no IO, no state — import and call cost_per_passed_gate(cost_usd, gates_passed).
"""

from __future__ import annotations


def cost_per_passed_gate(cost_usd: float, gates_passed: int) -> float | None:
    """Calculate the cost per passed gate.

    - Returns cost_usd / gates_passed as a float.
    - Returns 0.0 when cost_usd is 0 and gates_passed > 0.
    - Returns None when gates_passed <= 0.
    """
    if gates_passed <= 0:
        return None
    if cost_usd == 0:
        return 0.0
    return float(cost_usd / gates_passed)
