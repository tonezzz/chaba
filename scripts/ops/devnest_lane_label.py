#!/usr/bin/env python3
"""devnest-lane-label — pure lane classifier for DevNest dispatch chores.

Maps a free-text task description to one of the dispatch lanes declared
in docs/ssot/infrastructure/ssot.devnest-lanes.yml:

  codemod : L0 deterministic codemod arm — known-transform chores
            (config bump/retire/remove, purge, flag flip, registered
            rename). Deterministic fixes don't need an agent.
  manual  : terminal lane — Tony's hands: hardware purchases/installs,
            physical access, spend decisions, accounts.
  devin   : safe multi-step default — everything else.

Precedence: codemod > manual > devin. A text matching both codemod and
manual keywords resolves to codemod (deterministic transforms win);
the devin default is never wrong, just less cheap.

Pure function: no IO, no state — import and call lane_label(text).
"""

from __future__ import annotations

LANE_CODEMOD = "codemod"
LANE_MANUAL = "manual"
LANE_DEVIN = "devin"

_CODEMOD_KEYWORDS = ("purge", "config")
_MANUAL_KEYWORDS = ("physical", "hardware")


def lane_label(text: str) -> str:
    """Return the DevNest lane label for a task description."""
    lowered = (text or "").lower()
    if any(word in lowered for word in _CODEMOD_KEYWORDS):
        return LANE_CODEMOD
    if any(word in lowered for word in _MANUAL_KEYWORDS):
        return LANE_MANUAL
    return LANE_DEVIN


if __name__ == "__main__":
    import sys

    print(lane_label(" ".join(sys.argv[1:])))
