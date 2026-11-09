"""Regression harness for kanban-dispatch.py build_task — the dispatch
prompt is the highest-blast-radius artifact in the pipeline: pin the
rail contract (TASK_RAILS substitution, RETRY_RAILS on requeue,
REPORT_RAILS on report-linked cards), the KNOWN_PITFALLS primer
injection ordering/cap, and a byte tripwire on rail accretion.

Fixture cards replay historical dispatch scenarios as plain dicts
mirroring real card YAML shapes. Imports the dash-named module via
importlib; lp.build is monkeypatched (mock.patch.object, auto-restored)
so the primer path is deterministic — no dispatch, no git, no repo walk.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/kanban-dispatch.py"
sys.path.insert(0, str(REPO / "scripts" / "board"))  # dispatch_repos/lp imports

# rail accretion tripwire — raise only deliberately
FIXED_RAIL_BUDGET_BYTES = 6000

# Marker unique to the injected primer block — TASK_RAILS itself
# mentions "KNOWN_PITFALLS" in its outcome-doc instructions, so a bare
# substring check can't distinguish the block from the rails text.
PRIMER_MARK = "KNOWN_PITFALLS — lessons harvested"


def _load():
    spec = importlib.util.spec_from_file_location("kanban_dispatch", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card(**kw) -> dict:
    """Minimal real-shaped card: id/title/spec/note/action/report."""
    card = {"id": "fixture-card", "title": "fixture card",
            "action": {"type": "dispatch", "repo": "chaba"}}
    card.update(kw)
    return card


class BuildTaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def _task(self, card: dict, primer_lines=()) -> str:
        """build_task under a deterministic primer: lp.build returns
        primer_lines (empty = no matches) and KANBAN_PRIMER stays on."""
        with mock.patch.dict(os.environ, {"KANBAN_PRIMER": "1"}), \
             mock.patch.object(self.mod.lp, "build",
                               return_value=list(primer_lines)):
            return self.mod.build_task(card)

    def test_spec_verbatim_then_task_rails(self):
        card = _card(id="spec-card",
                     spec="Rebuild the frobnicate exactly.\nSecond line.")
        task = self._task(card)
        self.assertIn(card["spec"], task)
        self.assertLess(task.index(card["spec"]),
                        task.index("Rails: you are processing kanban card"))
        # {id}/{api} placeholders substituted
        self.assertIn("kanban card 'spec-card'", task)
        self.assertIn("docs/ssot/kanban/cards/spec-card.yml", task)
        self.assertIn(self.mod.API + "/comment", task)
        self.assertNotIn("{id}", task)
        self.assertNotIn("{api}", task)

    def test_retry_rails_on_requeue(self):
        card = _card(id="retry-card", spec="s",
                     action={"type": "dispatch", "repo": "chaba",
                             "attempts": 1, "last_failure": "boom"})
        task = self._task(card)
        self.assertIn("This is attempt 2", task)
        self.assertIn("boom", task)
        # absent for a fresh card
        fresh = self._task(_card(id="fresh-card", spec="s"))
        self.assertNotIn("This is attempt", fresh)

    def test_report_rails_on_report_linked(self):
        card = _card(id="rep-card", spec="s",
                     report="dispatch-health-scorecard")
        task = self._task(card)
        self.assertIn(
            "report-linked: ada-cms-pages/dispatch-health-scorecard", task)
        self.assertIn(
            "cms-report-note.py dispatch-health-scorecard --read", task)
        # absent without `report:`
        plain = self._task(_card(id="norep-card", spec="s"))
        self.assertNotIn("report-linked", plain)
        self.assertNotIn("cms-report-note.py", plain)

    def test_no_spec_falls_back_to_title_note(self):
        card = _card(id="nospec-card", title="Fix the frobnicate",
                     note="it broke on tuesday")
        task = self._task(card)
        self.assertIn("Fix the frobnicate", task)
        self.assertIn("it broke on tuesday", task)
        self.assertIn("Rails: you are processing kanban card", task)

    def test_primer_env_off_suppresses_block(self):
        """KANBAN_PRIMER=0: no KNOWN_PITFALLS even when lp.build has
        candidate lines to offer — and it is never consulted."""
        with mock.patch.dict(os.environ, {"KANBAN_PRIMER": "0"}), \
             mock.patch.object(self.mod.lp, "build",
                               return_value=["a lesson", "another"]) as b:
            task = self.mod.build_task(_card(spec="s"))
        b.assert_not_called()
        self.assertNotIn(PRIMER_MARK, task)

    def test_primer_block_ordering_and_cap(self):
        """Primer-on: KNOWN_PITFALLS lands after TASK_RAILS and before
        RETRY_RAILS/REPORT_RAILS, contributing <=8 lesson lines."""
        lines = [f"lesson line {i}" for i in range(8)]
        card = _card(id="primed-card", spec="s", report="r-slug",
                     action={"type": "dispatch", "repo": "chaba",
                             "attempts": 1, "last_failure": "boom"})
        task = self._task(card, primer_lines=lines)
        i_rails = task.index("Rails: you are processing kanban card")
        i_primer = task.index(PRIMER_MARK)
        i_retry = task.index("This is attempt 2")
        i_report = task.index("report-linked")
        self.assertLess(i_rails, i_primer)
        self.assertLess(i_primer, i_retry)
        self.assertLess(i_primer, i_report)
        block = task[i_primer:i_retry]
        bullets = [l for l in block.splitlines() if l.startswith("- ")]
        self.assertEqual(len(bullets), len(lines))
        self.assertLessEqual(len(bullets), 8)
        for line in lines:
            self.assertIn(f"- {line}", block)

    def test_rail_budget_tripwire(self):
        """Fixed-overhead byte budget: TASK_RAILS + RETRY_RAILS +
        REPORT_RAILS rendered with fixture values must stay under
        FIXED_RAIL_BUDGET_BYTES — a deliberate bump when rails accrete,
        not silent growth."""
        fixed = (
            self.mod.TASK_RAILS.format(id="budget-card", api=self.mod.API)
            + self.mod.RETRY_RAILS.format(
                id="budget-card", api=self.mod.API, n=2, failure="boom")
            + self.mod.REPORT_RAILS.format(slug="budget-slug"))
        total = len(fixed.encode("utf-8"))
        self.assertLessEqual(
            total, FIXED_RAIL_BUDGET_BYTES,
            f"fixed rail overhead grew to {total}B — bump "
            "FIXED_RAIL_BUDGET_BYTES only deliberately")


if __name__ == "__main__":
    unittest.main()
