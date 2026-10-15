"""Tests for scripts/board/answer-sweep.py — the triage half of the
request lifecycle (card knb-answer-action-triage).

Covers answer->verb classification (option action fields, option ids,
free-text hard verbs, the soft-assent gate on options asks), per-card
triage (single verb executes, conflicts defer, owned requests are
skipped, armed cards defer), and the noop receipt path.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "answer_sweep", REPO / "scripts" / "board" / "answer-sweep.py")
swe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(swe)

REF = "2026-10-15"


def req(rid, answer, **kw):
    r = {"id": rid, "ask": "q", "status": "answered", "answer": answer}
    r.update(kw)
    return r


def card(**kw):
    c = {"id": "t-card", "column": "backlog", "comms": []}
    c.update(kw)
    return c


class Classify(unittest.TestCase):
    def test_dict_option_action_field_wins(self):
        r = req("r1", "move-cache — Move caches to data disk",
                options=[{"id": "move-cache",
                          "label": "Move caches to data disk",
                          "action": "queue"}])
        self.assertEqual(swe.classify(r)[0], "queue")

    def test_dict_option_action_none(self):
        r = req("r1", "pin — Keep excluded",
                options=[{"id": "pin", "label": "Keep excluded",
                          "action": "none"}])
        self.assertEqual(swe.classify(r)[0], "none")

    def test_dict_option_id_is_the_verb(self):
        r = req("r1", "approve — Approve Phase B on tony-ha",
                options=[{"id": "approve", "label": "Approve Phase B"},
                         {"id": "hold", "label": "Hold"}])
        self.assertEqual(swe.classify(r)[0], "queue")

    def test_dict_option_decision_id_unmapped(self):
        r = req("r1", "two-pools — Two pools: tony-lane vs member/dev",
                options=[{"id": "per-instance", "label": "One key each"},
                         {"id": "two-pools", "label": "Two pools"}])
        self.assertIsNone(swe.classify(r)[0])

    def test_string_option_verbs(self):
        for ans, want in (("queue for dispatch ★", "queue"),
                          ("hold", "hold"),
                          ("close — not needed", "close"),
                          ("keep open — tail remains ★", "hold"),
                          ("stay free — parked queue covers it ★", "hold")):
            r = req("r1", ans, options=[ans])
            self.assertEqual(swe.classify(r)[0], want, ans)

    def test_free_text_hard_verbs_no_options(self):
        for ans, want in (("close this", "close"), ("hold it", "hold"),
                          ("yes", "queue"), ("approve.", "queue"),
                          ("retry", "retry")):
            r = req("r1", ans)
            self.assertEqual(swe.classify(r)[0], want, ans)

    def test_soft_assent_gated_on_options_ask(self):
        # 'yes' typed on a two-option ask that matches neither option is
        # not proof of intent — must not auto-queue
        r = req("r1", "yes", options=["close — done", "keep open"])
        self.assertIsNone(swe.classify(r)[0])

    def test_hard_verb_still_fires_as_free_text_on_options_ask(self):
        r = req("r1", "close it", options=["proceed", "hold"])
        self.assertEqual(swe.classify(r)[0], "close")

    def test_decisions_stay_unmapped(self):
        for ans in ("raise — Raise cap in AI Studio (spend)",
                    "move-cache — Move caches to data disk",
                    "recurring — recurring flood-check job",
                    "use same as gemini live."):
            self.assertIsNone(swe.classify(req("r1", ans))[0], ans)

    def test_noop_markers(self):
        for ans in ("superseded — re-raised with option buttons",
                    "duplicate — superseded by the newer ask",
                    "self-resolved — work landed elsewhere"):
            self.assertEqual(swe.classify(req("r1", ans))[0], "none", ans)


class Pending(unittest.TestCase):
    def test_skips_owned_prefixes(self):
        c = card(requests=[req("lab-review", "promote"),
                           req("merge-conflict", "Merge by hand"),
                           req("merge-conflict-2", "dropped")])
        self.assertEqual(swe.pending(c), [])

    def test_skips_executed_and_open(self):
        c = card(requests=[
            req("a", "queue", executed="2026-10-14 queue"),
            {"id": "b", "ask": "q2", "status": "open"}])
        self.assertEqual(swe.pending(c), [])

    def test_card_level_ask_included(self):
        c = card(ask={"question": "q", "status": "answered",
                      "answer": "yes"})
        self.assertEqual(len(swe.pending(c)), 1)


class TriageCard(unittest.TestCase):
    def test_queue_executes(self):
        c = card(requests=[req("r1", "queue for dispatch ★")],
                 awaiting_action=True)
        acted, notes = swe.triage_card(c, REF, [5])
        self.assertEqual(acted, ["r1"])
        self.assertEqual(c["action"]["status"], "queued")
        self.assertEqual(c["action"]["type"], "dispatch")
        self.assertEqual(c["requests"][0]["executed"], f"{REF} queue")
        self.assertFalse(swe.card_needs_triage(c))

    def test_hold_executes(self):
        c = card(column="review",
                 requests=[req("r1", "keep open — tail remains")])
        acted, _ = swe.triage_card(c, REF, [5])
        self.assertEqual(acted, ["r1"])
        self.assertEqual(c["action"]["status"], "idle")
        self.assertEqual(c["column"], "backlog")

    def test_close_executes_when_no_dispatch_session(self):
        c = card(column="review",
                 requests=[req("r1", "close — verified done ★")])
        acted, _ = swe.triage_card(c, REF, [5])
        self.assertEqual(acted, ["r1"])
        self.assertEqual(c["column"], "done")
        self.assertEqual(c["action"]["status"], "done")

    def test_conflict_defers(self):
        c = card(requests=[req("a", "queue it"), req("b", "close it")])
        acted, notes = swe.triage_card(c, REF, [5])
        self.assertEqual(acted, [])
        self.assertTrue(any("conflicting" in n for n in notes))
        self.assertNotIn("executed", c["requests"][0])

    def test_armed_card_stamps_queue_but_defers_close(self):
        c = card(action={"status": "running"},
                 requests=[req("a", "queue it"), req("b", "close it")])
        acted, notes = swe.triage_card(c, REF, [5])
        # two distinct verbs -> conflict even armed? queue would stamp,
        # close would defer — conflict check comes first
        self.assertTrue(any("conflicting" in n for n in notes))
        self.assertEqual(acted, [])

    def test_armed_queue_stamps(self):
        c = card(action={"status": "queued"},
                 requests=[req("a", "queue for dispatch")])
        acted, _ = swe.triage_card(c, REF, [5])
        self.assertEqual(acted, ["a"])
        self.assertIn("already queued", c["requests"][0]["executed"])

    def test_noop_stamps_without_action(self):
        c = card(requests=[req("a", "superseded — re-raised")])
        acted, notes = swe.triage_card(c, REF, [5])
        self.assertEqual(acted, ["a"])
        self.assertEqual(c["requests"][0]["executed"], f"{REF} none")
        self.assertNotIn("action", c)
        self.assertTrue(any("no board action" in n for n in notes))

    def test_unmapped_keeps_flag(self):
        c = card(awaiting_action=True,
                 requests=[req("a", "two-pools — Two pools")])
        acted, notes = swe.triage_card(c, REF, [5])
        self.assertEqual(acted, [])
        self.assertEqual(notes, [])
        self.assertTrue(swe.card_needs_triage(c))

    def test_budget_cap_defers(self):
        c = card(requests=[req("a", "queue it")])
        acted, notes = swe.triage_card(c, REF, [0])
        self.assertEqual(acted, [])
        self.assertTrue(any("MAX" in n for n in notes))
        self.assertNotIn("executed", c["requests"][0])


if __name__ == "__main__":
    unittest.main()
