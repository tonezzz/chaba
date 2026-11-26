"""Tests for scripts/board/answer-sweep.py — the triage half of the
request lifecycle (card knb-answer-action-triage).

Covers answer->verb classification (option action fields, option ids,
free-text hard verbs, the soft-assent gate on options asks), per-card
triage (single verb executes, conflicts defer, owned requests are
skipped, armed cards defer), and the noop receipt path.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

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
                          ("stay free — parked queue covers it ★", "hold"),
                          ("postpone — revisit next sprint", "hold")):
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

    def test_merge_conflict_explicit_action_executes(self):
        # KNB-0178 execute-answer: new merge-conflict asks carry dict
        # options with an explicit action — the answered choice must be
        # executable despite the owned prefix (resolve->queue, drop->
        # retry, hold->hold).
        opts = [
            {"id": "resolve", "action": "queue",
             "label": "let devin resolve the conflict and land it ★"},
            {"id": "drop", "action": "retry",
             "label": "drop this dispatch — re-dispatch fresh from main"},
            {"id": "hold", "action": "hold", "label": "hold the card"},
        ]
        for i, want in enumerate(("queue", "retry", "hold")):
            ans = f"{opts[i]['id']} — {opts[i]['label']}"
            r = req("merge-conflict", ans, options=opts)
            self.assertEqual(swe.classify(r)[0], want, ans)
            self.assertEqual(swe.pending(card(requests=[r])), [r], ans)
        # legacy string-option merge-conflict asks stay owned — no
        # retroactive execution of the ~50 historical answers
        legacy = req("merge-conflict", "let devin resolve it",
                     options=["let devin resolve it", "hold the card"])
        self.assertEqual(swe.pending(card(requests=[legacy])), [])

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

    def test_manual_executor_or_lane_queue_defers(self):
        for action in ({"type": "dispatch", "executor": "manual"},
                       {"type": "dispatch", "lane": "manual"}):
            c = card(action=dict(action, status="idle"),
                     requests=[req("r1", "queue it")])
            acted, notes = swe.triage_card(c, REF, [5])
            self.assertEqual(acted, [], action)
            self.assertTrue(any("manual" in n for n in notes), notes)
            self.assertNotEqual(c["action"].get("status"), "queued")

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


class SpecCompose(unittest.TestCase):
    """KNB-0180 option 2 phase 1 — when every ask is answered/closed/
    executed, awaiting_action is still set, and the card is an unarmed
    dispatch with no spec:, raise ONE consolidated spec-compose-<date>
    request inlining the answered asks+answers. Raise only — never
    arms dispatch; the spec-compose-* id is the re-raise guard."""

    def dead(self, **kw):
        c = card(awaiting_action=True,
                 action={"type": "dispatch", "status": "idle"},
                 requests=[
                     req("decide-pool", "two-pools — Two pools: "
                         "tony-lane vs member/dev"),
                     req("done-ask", "move-cache — Move caches",
                         executed=f"{REF} none")])
        c.update(kw)
        return c

    def test_ready_and_raises_single_consolidated_request(self):
        c = self.dead()
        self.assertTrue(swe.spec_compose_ready(c))
        rid = swe.raise_spec_compose(c, REF)
        self.assertEqual(rid, "spec-compose-2026-10-15")
        comp = c["requests"][-1]
        self.assertEqual(comp["id"], rid)
        self.assertEqual(comp["status"], "open")
        self.assertEqual(comp["from"], "chaba")
        # the answered asks+answers are inlined for the spec author
        self.assertIn("decide-pool", comp["ask"])
        self.assertIn("Two pools: tony-lane vs member/dev", comp["ask"])
        self.assertIn("done-ask", comp["ask"])
        self.assertIn("(executed)", comp["ask"])
        # options declare safe consequences — nothing may arm dispatch
        acts = {o.get("action") for o in comp["options"]}
        self.assertNotIn("queue", acts)
        self.assertNotIn("retry", acts)
        self.assertIn("hold", acts)
        self.assertIn("close", acts)
        # never auto-arm: action untouched
        self.assertEqual(c["action"]["status"], "idle")
        self.assertNotEqual(c["action"].get("status"), "queued")

    def test_open_request_blocks_until_answered_then_guard_holds(self):
        c = self.dead()
        swe.raise_spec_compose(c, REF)
        # the open spec-compose ask itself breaks 'all resolved'
        self.assertFalse(swe.spec_compose_ready(c))
        # once answered, the spec-compose-* id still guards re-raise
        c["requests"][-1].update(status="answered",
                                 answer="spec-written — done",
                                 executed=f"{REF} none")
        self.assertFalse(swe.spec_compose_ready(c))
        self.assertIsNone(swe.raise_spec_compose(c, REF))
        self.assertEqual(
            sum(1 for r in c["requests"]
                if str(r.get("id") or "").startswith("spec-compose-")),
            1)

    def test_prior_spec_compose_any_status_blocks(self):
        for st in ("open", "answered", "closed"):
            c = self.dead(requests=[
                req("spec-compose-2026-01-01", "prior raise", status=st),
                req("decide-pool", "two-pools — Two pools")])
            self.assertFalse(swe.spec_compose_ready(c), st)
            self.assertIsNone(swe.raise_spec_compose(c, REF), st)

    def test_requires_awaiting_action_flag(self):
        c = self.dead()
        c.pop("awaiting_action")
        self.assertFalse(swe.spec_compose_ready(c))

    def test_requires_dispatch_action_type(self):
        for action in (None, {"type": "manual"}, {"type": "script"},
                       "spec-review"):
            c = self.dead(action=action)
            self.assertFalse(swe.spec_compose_ready(c), action)

    def test_skips_armed_or_finished_action_status(self):
        for st in ("queued", "starting", "running", "done"):
            c = self.dead(action={"type": "dispatch", "status": st})
            self.assertFalse(swe.spec_compose_ready(c), st)

    def test_spec_or_column_gates(self):
        c = self.dead(spec="do the thing")
        self.assertFalse(swe.spec_compose_ready(c))
        # brief/note are NOT the dispatch spec — still ready without spec
        c = self.dead(brief="short summary", note="long notes")
        self.assertTrue(swe.spec_compose_ready(c))
        for col in ("done", "lab"):
            c = self.dead(column=col)
            self.assertFalse(swe.spec_compose_ready(c), col)

    def test_open_ask_blocks(self):
        c = self.dead(requests=[
            req("decide-pool", "two-pools — Two pools"),
            {"id": "still-open", "ask": "q", "status": "open"}])
        self.assertFalse(swe.spec_compose_ready(c))

    def test_all_executed_has_nothing_to_compose(self):
        # every ask executed -> pending() empty -> flag heals, no raise
        c = self.dead(requests=[
            req("a", "superseded — re-raised", executed=f"{REF} none")])
        self.assertFalse(swe.spec_compose_ready(c))

    def test_no_requests_no_raise(self):
        c = self.dead(requests=[])
        c.pop("ask", None)
        self.assertFalse(swe.spec_compose_ready(c))

    def test_card_level_ask_inlined(self):
        c = self.dead(requests=[],
                      ask={"question": "which pool?", "status": "answered",
                           "answer": "two-pools — Two pools"})
        self.assertTrue(swe.spec_compose_ready(c))
        rid = swe.raise_spec_compose(c, REF)
        comp = c["requests"][-1]
        self.assertEqual(comp["id"], rid)
        self.assertIn("which pool?", comp["ask"])
        self.assertIn("two-pools — Two pools", comp["ask"])

    def test_main_end_to_end_raises_once(self):
        c = self.dead()
        c["id"] = "t-card"
        with tempfile.TemporaryDirectory() as td:
            cdir = Path(td) / "cards"
            cdir.mkdir()
            (cdir / "t-card.yml").write_text(yaml.dump(c))
            old_dir, old_lock = swe.CARD_DIR, swe.LOCK
            swe.CARD_DIR, swe.LOCK = cdir, Path(td) / "board-api.lock"
            try:
                self.assertEqual(swe.main(cards=[dict(c)]), 0)
                # second pass — re-raise guard holds through main()
                after1 = yaml.safe_load((cdir / "t-card.yml").read_text())
                self.assertEqual(swe.main(cards=[after1]), 0)
                after = yaml.safe_load(
                    (cdir / "t-card.yml").read_text())
            finally:
                swe.CARD_DIR, swe.LOCK = old_dir, old_lock
        comps = [r for r in after["requests"]
                 if str(r.get("id") or "").startswith("spec-compose-")]
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0]["status"], "open")
        # detection + raise only: dispatch was never armed
        self.assertNotEqual(after["action"].get("status"), "queued")
        self.assertTrue(after.get("awaiting_action"))
        self.assertTrue(any("spec-compose" in str(m.get("text"))
                            for m in after.get("comms") or []))


if __name__ == "__main__":
    unittest.main()
