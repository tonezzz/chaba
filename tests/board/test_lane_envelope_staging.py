"""Queue-time lane_envelope staging (card
kanban-free-lane-routing-contract, DECISION 2026-11-26 Tony: adopt).

When a queued card's lane resolves to the opencode executor, board-api
stages action.lane_envelope + the declared routing fields so the
runner's claim gate sees the complete contract instead of holding the
card for "lane_envelope is not staged". The envelope must satisfy the
same admission contract runner-agent.prepare_profile_dispatch enforces
at start — these tests prove the staged shape actually passes it, that
the card claims on a capable host without manual pinning, and that the
executor=devin pin escape hatch is untouched.

No network, no git, no systemd — every seam is stubbed.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

os.environ["BOARD_API_COMMIT"] = "0"  # tmp card dirs aren't repo files

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
SCRIPT = REPO / "scripts" / "board" / "runner-agent.py"


def _load(name: str):
    if not name.endswith(".py"):
        name += ".py"
    spec = importlib.util.spec_from_file_location(
        name[:-3].replace("-", "_"), REPO / "scripts" / "board" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card(cid="c1", **fields):
    card = {"id": cid, "title": "weekly host health report",
            "spec": "collect the host facts and write the report",
            "column": "backlog", "action": {"type": "dispatch"}}
    card.update(fields)
    return card


class _ApiCase(unittest.TestCase):
    """board-api loaded with the same stubs test_queue_time_classify
    uses — comms/save/noop warners, no card dir writes."""

    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos")
        cls.api = _load("board-api")
        cls.api.dr = cls.dr

    def setUp(self):
        self.api.CARD_DIR = Path("/tmp/nonexistent")
        self.api.now = lambda: "2026-11-26T00:00:00Z"
        self.api.comms_add = lambda card, frm, text: card.setdefault(
            "comms", []).append({"from": frm, "text": text})
        self.api.save = lambda p, c: None
        self.api.queue_starve_warn = lambda c: ""
        self.api.queue_unclaimable_warn = lambda c: ""
        self.api.HOST = "localhost"

    def queue(self, card):
        return self.api.do_action(card, "queue", "devin")


class QueueEnvelopeStagingTest(_ApiCase):
    """do_action queue on a free_lane-classified card stages the whole
    opencode contract — envelope + executor/profile/host/class/artifact
    pins — in one shot."""

    def test_free_lane_card_gets_complete_envelope(self):
        # Author-pinned lane: master's queue-time kk_mac/claude auto-
        # routing preempts classified "report" cards before staging,
        # so the author-pinned path is the one that reaches this code.
        card = _card(action={"type": "dispatch", "lane": "free_lane"})
        res = self.queue(card)
        self.assertTrue(res.startswith("queued"), res)
        a = card["action"]
        self.assertEqual(a["lane"], "free_lane")
        # resolved executor declared — kanban-dispatch/devin paths
        # can never claim it
        self.assertEqual(a["executor"], "opencode")
        self.assertEqual(a["agent_profile"], "ops-readonly")
        self.assertEqual(a["task_class"], "report")
        self.assertEqual(a["target_host"], "idc02")
        self.assertEqual(a["artifact"],
                         "evals/opencode-lane/out/c1.json")
        env = a.get("lane_envelope")
        self.assertIsInstance(env, dict)
        for k in ("id", "card", "task_class", "stage", "target_host",
                  "executor", "model", "provider", "mcp_allowlist",
                  "allowed_paths", "artifact", "verifier",
                  "escalation", "rollback", "heartbeat"):
            self.assertIn(k, env, k)
        self.assertEqual(env["card"], "c1")
        self.assertEqual(env["profile"], "ops-readonly")
        self.assertEqual(env["stage"], "S3")
        self.assertEqual(env["target_host"], "idc02")
        self.assertEqual(env["executor"], "opencode")
        self.assertEqual(env["model"], "litellm/agent-local")
        self.assertEqual(env["provider"], "litellm")
        self.assertEqual(env["task_class"], "report")
        self.assertEqual(env["artifact"]["path"], a["artifact"])
        self.assertTrue(any("staged lane_envelope" in c["text"]
                            for c in card["comms"]))

    def test_staged_envelope_passes_lane_gate_lint_and_profile_check(self):
        """The staged shape must satisfy lane_gate.lint_envelope AND
        opencode_profiles.check_envelope against the real ops-readonly
        profile — the two gates prepare_profile_dispatch re-runs."""
        import sys as _sys
        _sys.path.insert(0, str(REPO / "scripts" / "devnest"))
        try:
            import lane_gate, opencode_profiles as ocp
        finally:
            _sys.path.remove(str(REPO / "scripts" / "devnest"))
        card = _card(action={"type": "dispatch", "lane": "free_lane"})
        self.queue(card)
        env = card["action"]["lane_envelope"]
        self.assertEqual(lane_gate.lint_envelope(env), [])
        prof = ocp.load_profile("ops-readonly")
        self.assertEqual(ocp.check_envelope(env, prof), [])
        # verifier must equal the profile's held-out verifier verbatim
        self.assertEqual(env["verifier"], prof["verifier"])
        self.assertEqual(env["artifact"]["schema"],
                         prof["artifact"]["schema"])

    def test_staged_envelope_passes_prepare_profile_dispatch(self):
        """End-to-end contract proof: the queued card's envelope is
        accepted by runner-agent.prepare_profile_dispatch on the
        qualified host — the exact check that used to hold the card."""
        mod = _load("runner-agent.py")
        ocp = mod.oc_profiles_module()
        prof = ocp.load_profile("ops-readonly")
        card = _card(action={"type": "dispatch", "lane": "free_lane"})
        self.queue(card)
        mod.HOST = "idc02"
        # the model the claim resolves: action.model unset -> lane pick
        model = mod.LANE_MODELS["free_lane"]
        self.assertEqual(model, "litellm/agent-local")
        frozen = mod.prepare_profile_dispatch(
            card, "tid-test-1", prof, model, ocp)
        self.assertEqual(frozen["id"], "tid-test-1")
        self.assertEqual(frozen["card"], "c1")
        self.assertEqual(frozen["stage"], "S3")
        self.assertEqual(frozen["model"], "litellm/agent-local")

    def test_staged_card_claims_on_capable_host(self):
        """runner-agent on an OPENCODE_LANES host claims the staged
        card — no lane_envelope hold, no manual pinning."""
        mod = _load("runner-agent.py")
        saved = {k: getattr(mod, k) for k in
                 ("OPENCODE_LANES", "DISPATCH", "LABELS", "HOST")}
        saved_fn = {k: getattr(mod, k) for k in
                    ("opencode_bin", "push_capable", "shutil_which")}
        try:
            mod.DISPATCH = str(SCRIPT)
            mod.push_capable = lambda repo: True
            mod.shutil_which = lambda name: True
            mod.LABELS = set()
            mod.OPENCODE_LANES = True
            mod.opencode_bin = lambda: "/x/opencode"
            card = _card(action={"type": "dispatch", "lane": "free_lane"})
            self.queue(card)
            mod.HOST = "idc02"
            self.assertEqual(mod.claimable(card), "dispatch")
            self.assertEqual(mod.executor_defer_reason(card), "")
            # a non-qualified host declines on the target_host pin —
            # it can never pass start-time admission anyway
            mod.HOST = "tony-dell"
            self.assertEqual(mod.claimable(card), "")
        finally:
            for k, v in {**saved, **saved_fn}.items():
                setattr(mod, k, v)


class QueueEnvelopeEscapeTest(_ApiCase):
    """The paths that must NOT get an auto-staged envelope."""

    def test_devin_pin_escape_hatch(self):
        """executor=devin is the author's own contract — queue keeps it,
        stages nothing, and the card stays on the devin path."""
        card = _card(action={"type": "dispatch", "executor": "devin",
                             "lane": "free_lane"})
        res = self.queue(card)
        self.assertTrue(res.startswith("queued"), res)
        a = card["action"]
        self.assertEqual(a["executor"], "devin")
        self.assertNotIn("lane_envelope", a)

    def test_devin_pin_still_claims_via_devin_path(self):
        mod = _load("runner-agent.py")
        saved = {k: getattr(mod, k) for k in
                 ("OPENCODE_LANES", "DISPATCH", "LABELS", "HOST")}
        saved_fn = {k: getattr(mod, k) for k in
                    ("opencode_bin", "push_capable", "shutil_which")}
        try:
            mod.DISPATCH = str(SCRIPT)
            mod.push_capable = lambda repo: True
            mod.shutil_which = lambda name: True
            mod.LABELS = set()
            mod.OPENCODE_LANES = True
            mod.opencode_bin = lambda: "/x/opencode"
            mod.HOST = "idc02"
            card = _card(action={"type": "dispatch", "executor": "devin",
                                 "lane": "free_lane"})
            self.queue(card)
            # executor=devin pins lane="" at start — it can never hit
            # the opencode route, so the unstaged hold must not touch it
            self.assertEqual(mod.claimable(card), "dispatch")
            self.assertEqual(mod.executor_defer_reason(card), "")
        finally:
            for k, v in {**saved, **saved_fn}.items():
                setattr(mod, k, v)

    def test_mutating_free_lane_card_keeps_hold(self):
        """A card with mutation intent must NOT get a read-only
        envelope — it would 'succeed' as a report and close with the
        wrong artifact. It stays on the staged-envelope/devin-pin hold."""
        card = _card(title="install the weekly report collector",
                     spec="install the collector and write the report",
                     action={"type": "dispatch", "lane": "free_lane"})
        res = self.queue(card)
        self.assertTrue(res.startswith("queued"), res)
        a = card["action"]
        self.assertEqual(a["lane"], "free_lane")
        self.assertNotIn("lane_envelope", a)
        self.assertNotEqual(a.get("executor"), "opencode")

    def test_paid_frontier_lane_not_staged(self):
        """paid_frontier has no LANE_PROFILES mapping — no profile
        resolves, so no envelope is staged."""
        card = _card(title="design a versus benchmark for the router",
                     spec="compare the two approaches")
        res = self.queue(card)
        self.assertTrue(res.startswith("queued"), res)
        a = card["action"]
        self.assertNotIn("lane_envelope", a)

    def test_non_opencode_lane_not_staged(self):
        card = _card(title="remove the deprecated config knob",
                     spec="drop the old setting")
        res = self.queue(card)
        self.assertTrue(res.startswith("queued"), res)
        self.assertNotIn("lane_envelope", card["action"])

    def test_author_staged_envelope_never_overwritten(self):
        custom = {"id": "hand-made", "card": "c1"}
        card = _card(action={"type": "dispatch", "lane": "free_lane",
                             "lane_envelope": custom})
        self.queue(card)
        self.assertEqual(card["action"]["lane_envelope"], custom)
        # and the author's own executor choice is untouched too
        self.assertNotEqual(card["action"].get("executor"), "opencode")

    def test_declared_executor_opencode_not_auto_staged(self):
        """executor=opencode is the author's contract — the queue does
        not fabricate an envelope for it (author stages their own)."""
        card = _card(action={"type": "dispatch", "executor": "opencode",
                             "lane": "free_lane"})
        self.queue(card)
        self.assertNotIn("lane_envelope", card["action"])

    def test_foreign_target_host_pin_blocks_staging(self):
        """A card pinned to a different host keeps its own route — the
        queue must not pin it to the staged host over the author's pin."""
        card = _card(action={"type": "dispatch", "lane": "free_lane",
                             "target_host": "tony-dell"})
        self.queue(card)
        a = card["action"]
        self.assertEqual(a["target_host"], "tony-dell")
        self.assertNotIn("lane_envelope", a)

    def test_declared_artifact_outside_lane_dirs_not_staged(self):
        card = _card(action={"type": "dispatch", "lane": "free_lane",
                             "artifact": "etc/passwd.json"})
        self.queue(card)
        self.assertNotIn("lane_envelope", card["action"])

    def test_foreign_repo_not_staged(self):
        """The lane's verifier/artifact roots resolve inside the card
        repo's dispatch worktree — a non-chaba card can never satisfy
        them, so it keeps the hold instead of burning a claim."""
        card = _card(action={"type": "dispatch", "lane": "free_lane",
                             "repo": "ada-voice"})
        self.queue(card)
        self.assertNotIn("lane_envelope", card["action"])

    def test_foreign_subject_host_not_staged(self):
        """subject_host is the remote-read contract's field; a staged
        non-remote envelope must not contradict a foreign declaration
        (prepare_profile_dispatch's subject_ok would fail at claim)."""
        card = _card(action={"type": "dispatch", "lane": "free_lane",
                             "subject_host": "tony-dell"})
        self.queue(card)
        self.assertNotIn("lane_envelope", card["action"])

    def test_non_staged_profile_not_staged(self):
        """agent_profile outside runner-agent's S3_STAGED_PROFILES
        (here the remote-read profile, which needs a subject_host +
        mcp_debug allowlist the queue can't derive) keeps the hold —
        staging it would burn a claim on admission failure."""
        card = _card(action={"type": "dispatch", "lane": "free_lane",
                             "agent_profile": "ops-remote-read"})
        self.queue(card)
        a = card["action"]
        self.assertNotIn("lane_envelope", a)
        self.assertNotEqual(a.get("executor"), "opencode")


class LaneEnvelopePlanUnitTest(unittest.TestCase):
    """dr.lane_envelope_plan directly — fail-safe returns None."""

    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos")

    def test_missing_profile_yaml_fails_safe(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            plan = self.dr.lane_envelope_plan(
                _card(), "free_lane", repo_root=td)
        self.assertIsNone(plan)

    def test_unmapped_lane_returns_none(self):
        self.assertIsNone(
            self.dr.lane_envelope_plan(_card(), "paid_frontier", REPO))
        self.assertIsNone(
            self.dr.lane_envelope_plan(_card(), "devin", REPO))
        self.assertIsNone(
            self.dr.lane_envelope_plan(_card(), "manual", REPO))

    def test_declared_task_class_respected(self):
        card = _card(action={"type": "dispatch", "lane": "free_lane",
                             "task_class": "read_only"})
        plan = self.dr.lane_envelope_plan(card, "free_lane", REPO)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["envelope"]["task_class"], "read_only")
        self.assertEqual(plan["action"]["task_class"], "read_only")

    def test_unadmitted_declared_task_class_rejected(self):
        card = _card(action={"type": "dispatch", "lane": "free_lane",
                             "task_class": "branch_code"})
        self.assertIsNone(
            self.dr.lane_envelope_plan(card, "free_lane", REPO))

    def test_author_model_pin_propagates_to_envelope(self):
        card = _card(action={"type": "dispatch", "lane": "free_lane",
                             "model": "litellm/gemini-3.5-flash"})
        plan = self.dr.lane_envelope_plan(card, "free_lane", REPO)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["envelope"]["model"],
                         "litellm/gemini-3.5-flash")
        self.assertEqual(plan["envelope"]["provider"], "litellm")


class LaneTableLockstepTest(unittest.TestCase):
    """runner-agent's vendored lane tables must mirror dispatch_repos —
    the staged envelope's model/profile resolution depends on both
    sides agreeing (the OPS-1363 free_lane->agent-local repoint drifted
    once already)."""

    def test_lane_models_in_lockstep(self):
        dr = _load("dispatch_repos")
        ra = _load("runner-agent.py")
        self.assertEqual(dr.LANE_MODELS, ra.LANE_MODELS)
        self.assertEqual(dr.DEVIN_LANE_MODELS, ra.DEVIN_LANE_MODELS)

    def test_lane_profiles_in_lockstep(self):
        dr = _load("dispatch_repos")
        ra = _load("runner-agent.py")
        self.assertEqual(dr.LANE_PROFILES, ra.LANE_PROFILES)


if __name__ == "__main__":
    unittest.main()
