"""Regression tests for the dispatch-lane branch of runner-agent.start_task.

OPS-0846 review (2026-10-25): `lane` was only bound inside the
`if not a.get("lane")` classify block, so any card that already carried
action.lane — an explicit lane, or one persisted by the JEV_LANE
claim-classify — hit `if lane in LANE_MODELS` unbound and crashed the
claim with UnboundLocalError (card stayed claimed, no unit started).
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _card(**action_kw):
    a = {"type": "dispatch", "status": "queued", "repo": "chaba"}
    a.update(action_kw)
    return {"id": "lane-card", "title": "lane test", "spec": "do a thing",
            "action": a}


class StartTaskLaneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in
                       ("OPENCODE_LANES", "DISPATCH", "HOST")}
        self._saved_fn = {k: getattr(m, k) for k in
                          ("sh", "classify_lane", "start_opencode_lane",
                           "dr_module", "enforce_task_limits")}
        m.DISPATCH = str(SCRIPT)          # exists -> dispatch executor present
        m.dr_module = lambda: None        # no host checkout resolution
        m.enforce_task_limits = lambda *a, **k: None
        self.calls = []
        m.sh = lambda argv, **kw: self.calls.append(argv) or _proc(
            0, "fake-tid-123\n")

    def tearDown(self):
        m = self.mod
        for k, v in self._saved.items():
            setattr(m, k, v)
        for k, v in self._saved_fn.items():
            setattr(m, k, v)

    def test_explicit_lane_devin_path_does_not_crash(self):
        """Card with action.lane already set + OPENCODE_LANES=0 must
        dispatch through devin-dispatch, not raise UnboundLocalError."""
        self.mod.OPENCODE_LANES = False
        unit, tid, err = self.mod.start_task(
            _card(lane="free_lane",
                  model="litellm/gemini-3.5-flash-lite"), "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(unit, "devin-task-fake-tid-123")
        self.assertEqual(tid, "fake-tid-123")

    def test_explicit_lane_routes_to_opencode_when_enabled(self):
        """Explicit model lane + OPENCODE_LANES=1 -> OpenCode executor."""
        self.mod.OPENCODE_LANES = True
        seen = []
        self.mod.start_opencode_lane = lambda card, lane, unit: (
            seen.append(lane) or ("devin-task-x", "x", ""))
        unit, tid, err = self.mod.start_task(
            _card(lane="free_lane"), "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(seen, ["free_lane"])
        self.assertEqual(unit, "devin-task-x")

    def test_unset_lane_classifies_and_persists(self):
        """Unset lane -> classify_lane result persisted on the action."""
        self.mod.OPENCODE_LANES = False
        self.mod.classify_lane = lambda card: ("paid_frontier", "kw", 1.0)
        card = _card()
        unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(card["action"]["lane"], "paid_frontier")
        self.assertEqual(card["action"]["model"],
                         "litellm/gemini-2.5-flash")

    def test_unset_lane_classified_free_lane_uses_opencode(self):
        self.mod.OPENCODE_LANES = True
        self.mod.classify_lane = lambda card: ("free_lane", "kw", 1.0)
        seen = []
        self.mod.start_opencode_lane = lambda card, lane, unit: (
            seen.append(lane) or ("devin-task-y", "y", ""))
        card = _card()
        unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(seen, ["free_lane"])

    def test_litellm_model_dropped_on_devin_path(self):
        """OPS-1127: a stale/lane-mapped litellm/* action.model must never
        reach the devin path — the CLI rejects foreign provider ids at
        launch. The guard drops it -> devin default model."""
        self.mod.OPENCODE_LANES = False
        envs = []

        def fake_sh(argv, **kw):
            self.calls.append(argv)
            envs.append(kw.get("env") or {})
            return _proc(0, "fake-tid-123\n")

        self.mod.sh = fake_sh
        card = _card(lane="devin", model="litellm/gemini-3.5-flash-lite")
        unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(err, "")
        self.assertTrue(envs)
        self.assertNotIn("DISPATCH_MODEL", envs[0])
        self.assertEqual(envs[0].get("DISPATCH_PROVIDER"), "devin")

    def test_devin_model_survives_on_devin_path(self):
        """Same guard must leave a native devin model id in place."""
        self.mod.OPENCODE_LANES = False
        envs = []

        def fake_sh(argv, **kw):
            envs.append(kw.get("env") or {})
            return _proc(0, "fake-tid-123\n")

        self.mod.sh = fake_sh
        card = _card(lane="devin", model="swe-2-flash")
        unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(err, "")
        self.assertTrue(envs)
        self.assertEqual(envs[0].get("DISPATCH_MODEL"), "swe-2-flash")
        self.assertEqual(envs[0].get("DISPATCH_PROVIDER"), "devin")

    def test_classified_manual_is_refused_not_dispatched(self):
        """manual lane = Tony's hands — fail loudly, never burn tokens."""
        self.mod.classify_lane = lambda card: ("manual", "kw", 1.0)
        card = _card()
        unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(unit, "")
        self.assertIn("manual", err)
        self.assertFalse(self.calls)  # no devin-dispatch spawn
        self.assertNotIn("lane", card["action"])  # manual never persisted


class CollectTest(unittest.TestCase):
    """runner-agent.collect — the 'finished (ok)' lie
    (dispatch-empty-closeout-verification-gap): systemd-run --collect
    unloads the unit at exit, and `systemctl show` on a not-loaded unit
    reports ExecMainStatus=0/Result=success DEFAULTS. collect() must
    read real evidence instead: task-dir exit_code > loaded-unit fields
    > journal Succeeded/Failed lines; no record -> NOT ok."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._sh = m.sh
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self._home_old = os.environ.get("HOME")
        os.environ["HOME"] = self.td.name
        self.addCleanup(self._restore_home)
        self.unit = "devin-task-20260101-000000-t"
        self.tdir = (Path(self.td.name) / ".local/share/devin-dispatch"
                     "/tasks/20260101-000000-t")
        self.tdir.mkdir(parents=True)

    def _restore_home(self):
        if self._home_old is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._home_old

    def tearDown(self):
        self.mod.sh = self._sh

    def _stub(self, loadstate="not-found", result="success",
              exec_status="0", journal=""):
        """Collected-unit defaults are not evidence of successful exit."""
        def fake_sh(argv, **kw):
            if argv[:3] == ["systemctl", "--user", "show"]:
                return _proc(0, f"ExecMainStatus={exec_status}\n"
                                f"Result={result}\n"
                                f"LoadState={loadstate}\n")
            if argv[0] == "journalctl":
                return _proc(0, journal)
            return _proc(0)
        self.mod.sh = fake_sh

    def test_collected_unit_defaults_are_not_ok(self):
        (self.tdir / "exit_code").write_text("1\n")
        self._stub(loadstate="not-found",
                   journal="devin-task-x.service: Failed with result "
                           "'exit-code'.\n")
        ok, res = self.mod.collect(self.unit)
        self.assertFalse(ok)
        self.assertIn("exit=1", res)

    def test_exit_code_zero_is_ok(self):
        (self.tdir / "exit_code").write_text("0\n")
        self._stub(loadstate="not-found")
        ok, res = self.mod.collect(self.unit)
        self.assertTrue(ok)
        self.assertIn("exit=0", res)

    def test_loaded_unit_fields_used(self):
        self._stub(loadstate="loaded", result="exit-code",
                   exec_status="1")
        ok, res = self.mod.collect(self.unit)
        self.assertFalse(ok)
        self.assertIn("exit=1", res)

    def test_journal_failed_when_unit_gone(self):
        self._stub(loadstate="not-found",
                   journal="devin-task-x.service: Failed with result "
                           "'exit-code'.\n")
        ok, res = self.mod.collect(self.unit)
        self.assertFalse(ok)
        self.assertIn("journal=exit-code", res)

    def test_journal_succeeded_when_unit_gone(self):
        self._stub(loadstate="not-found",
                   journal="devin-task-x.service: Succeeded.\n")
        ok, res = self.mod.collect(self.unit)
        self.assertTrue(ok)
        self.assertIn("journal=success", res)

    def test_no_record_is_unproven_not_ok(self):
        self._stub(loadstate="not-found")
        ok, res = self.mod.collect("runner-c1-1700000000")
        self.assertFalse(ok)
        self.assertIn("no exit record", res)

    def _exit_file(self, unit, code):
        """OPS-1181 fixture — the runner-* wrapper's durable exit record."""
        d = Path(f"/run/user/{os.getuid()}/runner-exit")
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{unit}.code"
        p.write_text(f"{code}\n")
        self.addCleanup(lambda: p.unlink(missing_ok=True))
        return p

    def test_runner_exit_file_ok_when_unit_reaped(self):
        unit = "runner-ops1181-ok"
        self._exit_file(unit, "0")
        # GC'd unit: no fields, no journal — the exit file alone proves it
        self._stub(loadstate="not-found", journal="")
        ok, res = self.mod.collect(unit)
        self.assertTrue(ok)
        self.assertIn("exit=0", res)

    def test_runner_exit_file_nonzero_fails(self):
        unit = "runner-ops1181-fail"
        self._exit_file(unit, "2")
        self._stub(loadstate="not-found", journal="")
        ok, res = self.mod.collect(unit)
        self.assertFalse(ok)
        self.assertIn("exit=2", res)

    def test_runner_exit_file_removed_after_read(self):
        unit = "runner-ops1181-gc"
        p = self._exit_file(unit, "0")
        self._stub(loadstate="not-found", journal="")
        self.mod.collect(unit)
        self.assertFalse(p.exists())

    def test_journal_deactivated_successfully_is_ok(self):
        # a GC'd simple service logs "Deactivated successfully." — not
        # "Succeeded." (oneshot-only); the pattern must cover both
        self._stub(loadstate="not-found",
                   journal="runner-x.service: Deactivated successfully.\n")
        ok, res = self.mod.collect("runner-c2-1700000000")
        self.assertTrue(ok)
        self.assertIn("journal=success", res)


class ClaimPassLaneTest(unittest.TestCase):
    """OPS-0885: an explicit action.lane pinned in the card YAML must
    survive claim_pass. Under JEV_LANE=1 the pre-fix code re-classified
    unconditionally and clobbered pinned free_lane cards into
    codemod/paid_frontier lanes (doc card -> codemod, code card ->
    paid_frontier spend) — the exact miss the pilot pins against."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved_env = os.environ.get("JEV_LANE")
        os.environ["JEV_LANE"] = "1"
        self._saved = {k: getattr(m, k) for k in
                       ("DISPATCH",)}
        self._saved_fn = {k: getattr(m, k) for k in
                          ("api", "start_task", "push_capable",
                           "gpu_preflight", "classify_lane", "dr_module",
                           "overloaded", "note_defer")}
        m.DISPATCH = str(SCRIPT)  # exists -> dispatch executor present
        m.dr_module = lambda: None
        m.push_capable = lambda repo: True
        m.gpu_preflight = lambda card: ""
        m.overloaded = lambda: False
        m.note_defer = lambda *a, **k: None
        m.start_task = lambda card, typ: ("devin-task-t", "t", "")
        self.posts = []
        self.cards = []
        self.classified = []

        def fake_api(path, body=None):
            if path == "/cards":
                return {"cards": self.cards}
            self.posts.append((path, dict(body or {})))
            return {}
        m.api = fake_api
        m.classify_lane = lambda card: (
            self.classified.append(card.get("id")) or ("paid_frontier", "kw", 1.0))

    def tearDown(self):
        m = self.mod
        if self._saved_env is None:
            os.environ.pop("JEV_LANE", None)
        else:
            os.environ["JEV_LANE"] = self._saved_env
        for k, v in self._saved.items():
            setattr(m, k, v)
        for k, v in self._saved_fn.items():
            setattr(m, k, v)

    def _claim_bodies(self):
        return [b for p, b in self.posts
                if p == "/action" and b.get("do") == "claim"]

    def test_pinned_lane_survives_claim_classification(self):
        self.cards = [_card(lane="free_lane",
                            model="litellm/gemini-3.5-flash-lite")]
        self.assertTrue(self.mod.claim_pass({}))
        bodies = self._claim_bodies()
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0]["lane"], "free_lane")
        self.assertEqual(bodies[0]["model"],
                         "litellm/gemini-3.5-flash-lite")
        self.assertEqual(self.classified, [])  # never consulted

    def test_pinned_lane_gets_lane_model_when_unset(self):
        self.cards = [_card(lane="free_lane")]
        self.assertTrue(self.mod.claim_pass({}))
        bodies = self._claim_bodies()
        self.assertEqual(bodies[0]["model"],
                         "litellm/gemini-3.5-flash-lite")

    def test_unset_lane_still_classifies_at_claim(self):
        self.cards = [_card()]
        self.assertTrue(self.mod.claim_pass({}))
        bodies = self._claim_bodies()
        self.assertEqual(bodies[0]["lane"], "paid_frontier")
        self.assertEqual(bodies[0]["model"],
                         "litellm/gemini-2.5-flash")
        self.assertEqual(self.classified, ["lane-card"])


class ClaimPassScriptOnlyTest(unittest.TestCase):
    """OPS-1182 + KNB-1183: the host-overload gate must not starve
    cheap script claims, and any host-level skip must leave a
    card-visible defer note — 'claim pass skipped' in a journal
    nobody greps is silent starvation."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved_env = os.environ.get("JEV_LANE")
        os.environ["JEV_LANE"] = "0"
        self._saved = {k: getattr(m, k) for k in ("DISPATCH",)}
        self._saved_fn = {k: getattr(m, k) for k in
                          ("api", "start_task", "push_capable",
                           "gpu_preflight", "classify_lane", "dr_module",
                           "overloaded", "note_defer")}
        m.DISPATCH = str(SCRIPT)
        m.dr_module = lambda: None
        m.push_capable = lambda repo: True
        m.gpu_preflight = lambda card: ""
        m.classify_lane = lambda card: ("paid_frontier", "kw", 1.0)
        self.posts = []
        self.cards = []
        self.defers = []
        m.note_defer = lambda card, kind, reason, **kw: \
            self.defers.append((card.get("id"), kind, reason))
        m.start_task = lambda card, typ: ("devin-task-t", "t", "")

        def fake_api(path, body=None):
            if path == "/cards":
                return {"cards": self.cards}
            self.posts.append((path, dict(body or {})))
            return {}
        m.api = fake_api

    def tearDown(self):
        m = self.mod
        if self._saved_env is None:
            os.environ.pop("JEV_LANE", None)
        else:
            os.environ["JEV_LANE"] = self._saved_env
        for k, v in self._saved.items():
            setattr(m, k, v)
        for k, v in self._saved_fn.items():
            setattr(m, k, v)

    def _two_cards(self):
        sc = _card(type="script")
        sc["id"] = "script-card"
        sc["action"]["script"] = {"repo": "chaba", "cmd": "true"}
        dc = _card()
        dc["id"] = "dispatch-card"
        self.cards = [sc, dc]

    def _claim_ids(self):
        return [b["id"] for p, b in self.posts
                if p == "/action" and b.get("do") == "claim"]

    def test_overloaded_host_still_claims_script(self):
        # heavy cap exceeded, script cap fine -> script-only pass
        self.mod.overloaded = lambda pc=None: pc is None
        self._two_cards()
        self.assertTrue(self.mod.claim_pass({}))
        self.assertEqual(self._claim_ids(), ["script-card"])
        # the dispatch card gets the host-gate note; the script card is
        # exempt — it was claimable under this same pass
        kinds = {cid: kind for cid, kind, _ in self.defers}
        self.assertEqual(kinds.get("dispatch-card"), "hostgate")
        self.assertNotIn("script-card", kinds)
        self.assertIn("overloaded", next(
            r for c, k, r in self.defers if c == "dispatch-card"))

    def test_hard_skip_notes_every_queued_card(self):
        # script cap also exceeded -> full skip, notes on both
        self.mod.overloaded = lambda pc=None: True
        self._two_cards()
        self.assertFalse(self.mod.claim_pass({}))
        self.assertEqual(self._claim_ids(), [])
        noted = {cid for cid, kind, _ in self.defers
                 if kind == "hostgate"}
        self.assertEqual(noted, {"script-card", "dispatch-card"})

    def test_no_notes_for_foreign_pins(self):
        # a card pinned to another host is not this host's to explain
        self.mod.overloaded = lambda pc=None: True
        foreign = _card(target_host="some-other-host")
        foreign["id"] = "foreign-card"
        self.cards = [foreign]
        self.assertFalse(self.mod.claim_pass({}))
        self.assertEqual(self.defers, [])


if __name__ == "__main__":
    unittest.main()
