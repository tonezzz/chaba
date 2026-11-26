"""Tests for the nest-mgr v2 actuation plane (card nest-mgr-v2-actuation).

Covers mode resolution (env/file/kill/circuit), the restart gate
never-list vs allowlist ordering, throttle limits, the audit event
stream, per-unit and per-host circuit breakers, and the plan_only
guarantee that a dry-run/report can never execute."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "stacks" / "services" / "nest-mgr" / "nest-mgr.py"

spec = importlib.util.spec_from_file_location("nest_mgr", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["nest_mgr"] = mod
spec.loader.exec_module(mod)


def iso_ago(seconds: float) -> str:
    return (mod._now() - timedelta(seconds=seconds)).isoformat(
        timespec="seconds")


def node(unit="jev-x.service", state="failed", owner="manager",
         restart_ok=False, topo_status=None, name="jev-x",
         restart_policy="always"):
    return {"name": name, "unit": unit, "state": state, "owner": owner,
            "restart_ok": restart_ok, "topo_status": topo_status,
            "restart_policy": restart_policy, "sources": ["unit"]}


class FlagsCase(unittest.TestCase):
    """Each test gets a fresh flag dir; module-level flag paths are
    patched to point inside it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.d = d
        self._p = []
        for attr, val in {
                "STATE_DIR": d, "MODE_FILE": d / "mode",
                "KILL_FILE": d / "actuation.off",
                "OPTIN_FILE": d / "actuation.on",
                "HOST_CIRCUIT": d / "host-circuit.open",
                "MANUAL_FILE": d / "manual-units",
                "ALLOW_FILE": d / "restart-allowlist",
                "CIRCUIT_DIR": d / "circuit",
        }.items():
            self._p.append(patch.object(mod, attr, val))
            self._p[-1].start()
        self._p.append(patch.dict(mod.os.environ, {}, clear=False))
        self._p[-1].start()
        mod.os.environ.pop("NEST_MGR_MODE", None)
        mod.os.environ.pop("NEST_MGR_PROD_OK", None)

    def tearDown(self):
        for p in self._p:
            p.stop()
        self.tmp.cleanup()

    def tick(self, nodes, prev=None, plan_only=False, mode=None):
        if mode is not None:
            mod.os.environ["NEST_MGR_MODE"] = mode
        return mod.actuation_tick(nodes, FakeHid(), prev or {},
                                  plan_only=plan_only)


class FakeHid:
    hostname = "test-host"
    ts_ip = "100.0.0.1"

    def label(self):
        return "test-host"


class TestModes(FlagsCase):
    def test_default_is_monitor(self):
        self.assertEqual(mod.requested_mode(), "monitor")

    def test_env_wins_over_file(self):
        (self.d / "mode").write_text("guarded")
        mod.os.environ["NEST_MGR_MODE"] = "recommend"
        self.assertEqual(mod.requested_mode(), "recommend")

    def test_file_when_no_env(self):
        (self.d / "mode").write_text("recommend\n")
        self.assertEqual(mod.requested_mode(), "recommend")

    def test_garbage_falls_back_to_monitor(self):
        (self.d / "mode").write_text("yolo")
        self.assertEqual(mod.requested_mode(), "monitor")

    def test_kill_switch_forces_monitor(self):
        (self.d / "actuation.off").touch()
        eff, notes = mod.effective_mode("guarded")
        self.assertEqual(eff, "monitor")
        self.assertTrue(notes)

    def test_host_circuit_forces_monitor(self):
        (self.d / "host-circuit.open").touch()
        eff, _ = mod.effective_mode("guarded")
        self.assertEqual(eff, "monitor")

    def test_guarded_needs_opt_in(self):
        eff, _ = mod.effective_mode("guarded")
        self.assertEqual(eff, "recommend")
        (self.d / "actuation.on").touch()
        eff, _ = mod.effective_mode("guarded")
        self.assertEqual(eff, "guarded")


class TestRestartGate(FlagsCase):
    def test_allowlisted_passes(self):
        self.assertIsNone(mod.restart_gate(
            node(restart_ok=True), set(), set()))
        self.assertIsNone(mod.restart_gate(
            node(), {"jev-x.service"}, set()))

    def test_not_allowlisted(self):
        self.assertEqual(mod.restart_gate(node(), set(), set()),
                         "not-allowlisted")

    def test_never_list_beats_allowlist(self):
        # card-owned + allowlisted => still never
        self.assertEqual(mod.restart_gate(
            node(owner="card:foo", restart_ok=True), set(), set()),
            "owner-card")
        self.assertEqual(mod.restart_gate(
            node(owner="unmanaged", restart_ok=True), set(), set()),
            "unmanaged")
        self.assertEqual(mod.restart_gate(
            node(restart_ok=True), set(), {"jev-x.service"}), "manual")
        self.assertEqual(mod.restart_gate(
            node(topo_status="prod", restart_ok=True), set(), set()),
            "production")

    def test_prod_override_env(self):
        mod.os.environ["NEST_MGR_PROD_OK"] = "1"
        self.assertIsNone(mod.restart_gate(
            node(topo_status="prod", restart_ok=True), set(), set()))

    def test_self_never_restart(self):
        self.assertEqual(mod.restart_gate(
            node(unit="nest-mgr.service", restart_ok=True), set(),
            set()), "self")

    def test_on_success_policy_skipped(self):
        self.assertEqual(mod.restart_gate(
            node(restart_ok=True, restart_policy="on-success"),
            set(), set()), "restart-policy")

    def test_unit_circuit_blocks(self):
        circ = self.d / "circuit"
        circ.mkdir()
        (circ / "jev-x.service.open").touch()
        self.assertEqual(mod.restart_gate(
            node(restart_ok=True), set(), set()), "circuit-open")


class TestThrottle(FlagsCase):
    def test_cooldown(self):
        u = {"attempts": [{"ts": iso_ago(60), "ok": True}]}
        self.assertEqual(mod.throttle_gate(u), "cooldown")

    def test_rate_limit(self):
        u = {"attempts": [{"ts": iso_ago(600), "ok": True},
                          {"ts": iso_ago(1200), "ok": True}]}
        self.assertEqual(mod.throttle_gate(u), "rate-limit")

    def test_old_attempts_dont_count(self):
        u = {"attempts": [{"ts": iso_ago(7200), "ok": True},
                          {"ts": iso_ago(3700), "ok": True}]}
        self.assertIsNone(mod.throttle_gate(u))


class TestTick(FlagsCase):
    def failed_node(self, **kw):
        return {"k": node(**kw)}

    def prev_with_streak(self, unit="jev-x.service", streak=3):
        return {"actuation": {"units": {unit: {"fail_ticks": streak}}},
                "actions": []}

    def test_monitor_emits_nothing_but_counts(self):
        nodes = self.failed_node(restart_ok=True)
        act, ev = self.tick(nodes, self.prev_with_streak(), mode="monitor")
        self.assertEqual(ev, [])
        self.assertEqual(act["units"]["jev-x.service"]["fail_ticks"], 4)

    def test_recommend_logs_and_executes_nothing(self):
        nodes = self.failed_node(restart_ok=True)
        with patch.object(mod, "_sh",
                          return_value=("", 0)) as sh:
            act, ev = self.tick(nodes, self.prev_with_streak(),
                                mode="recommend")
        sh.assert_not_called()
        kinds = [(e["action"], e["outcome"]) for e in ev]
        self.assertIn(("restart", "recommended"), kinds)

    def test_recommend_needs_three_ticks(self):
        nodes = self.failed_node(restart_ok=True)
        _, ev = self.tick(nodes, self.prev_with_streak(streak=1),
                          mode="recommend")
        self.assertFalse([e for e in ev if e["action"] == "restart"])

    def test_recommend_deduped(self):
        prev = self.prev_with_streak()
        prev["actuation"]["units"]["jev-x.service"]["last_rec"] = \
            iso_ago(60)
        _, ev = self.tick(self.failed_node(restart_ok=True), prev,
                          mode="recommend")
        self.assertFalse([e for e in ev if e["outcome"] == "recommended"])

    def test_held_event_for_blocked_unit(self):
        _, ev = self.tick(self.failed_node(), self.prev_with_streak(),
                          mode="recommend")
        held = [e for e in ev if e["outcome"] == "held"]
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]["reason"], "not-allowlisted")

    def test_guarded_executes_allowlisted(self):
        (self.d / "actuation.on").touch()
        with patch.object(mod, "_sh", return_value=("", 0)) as sh:
            act, ev = self.tick(self.failed_node(restart_ok=True),
                                self.prev_with_streak(), mode="guarded")
        sh.assert_called_once_with(
            ["systemctl", "--user", "restart", "jev-x.service"],
            timeout=30)
        self.assertIn(("restart", "ok"),
                      [(e["action"], e["outcome"]) for e in ev])
        self.assertEqual(
            act["units"]["jev-x.service"]["fail_ticks"], 0)

    def test_plan_only_never_executes(self):
        (self.d / "actuation.on").touch()
        with patch.object(mod, "_sh", return_value=("", 0)) as sh:
            act, ev = self.tick(self.failed_node(restart_ok=True),
                                self.prev_with_streak(), plan_only=True,
                                mode="guarded")
        sh.assert_not_called()
        self.assertEqual(act["mode"], "recommend")
        self.assertIn(("restart", "recommended"),
                      [(e["action"], e["outcome"]) for e in ev])

    def test_unit_circuit_after_two_failures(self):
        (self.d / "actuation.on").touch()
        prev = self.prev_with_streak()
        # one failed attempt 10 min ago — outside cooldown
        prev["actuation"]["units"]["jev-x.service"]["attempts"] = [
            {"ts": iso_ago(600), "ok": False}]
        with patch.object(mod, "_sh", return_value=("", 1)):
            _, ev = self.tick(self.failed_node(restart_ok=True), prev,
                              mode="guarded")
        self.assertTrue(
            (self.d / "circuit" / "jev-x.service.open").exists())
        self.assertIn(("circuit-open", "open"),
                      [(e["action"], e["outcome"]) for e in ev])

    def test_host_circuit_over_budget(self):
        (self.d / "actuation.on").touch()
        prev = self.prev_with_streak()
        prev["actions"] = [
            {"ts": iso_ago(300), "host": "test-host",
             "unit": f"u{i}.service", "action": "restart",
             "outcome": "ok"} for i in range(5)]
        with patch.object(mod, "_sh", return_value=("", 0)) as sh:
            act, ev = self.tick(self.failed_node(restart_ok=True), prev,
                                mode="guarded")
        sh.assert_not_called()
        self.assertTrue((self.d / "host-circuit.open").exists())
        self.assertEqual(act["mode"], "recommend")

    def test_mode_change_recorded(self):
        _, ev = self.tick(self.failed_node(), {"actuation": {
            "mode": "monitor"}}, mode="recommend")
        self.assertIn(("mode-change", "recommend"),
                      [(e["action"], e["outcome"]) for e in ev])


class TestGhostPrune(FlagsCase):
    """Units that leave discovery must not keep actuation state forever
    (idc02 ghost: ada-code.service outlived its unit file)."""

    def chain(self, nodes, act, ticks):
        prev_act = act
        for _ in range(ticks):
            prev_act, _ = self.tick(nodes, {"actuation": prev_act,
                                            "actions": []},
                                    mode="recommend")
        return prev_act

    def ghost_prev(self):
        return {"requested_mode": "recommend", "mode": "recommend",
                "units": {"ghost.service": {
                    "fail_ticks": 56,
                    "held": {"gate": "not-allowlisted",
                             "ts": iso_ago(3600)}}},
                "metrics": {}}

    def test_ghost_pruned_after_misses(self):
        act = self.chain({}, self.ghost_prev(), mod.UNIT_PRUNE_MISSES)
        self.assertNotIn("ghost.service", act["units"])

    def test_ghost_kept_within_grace(self):
        act = self.chain({}, self.ghost_prev(), 5)
        self.assertIn("ghost.service", act["units"])
        self.assertEqual(act["units"]["ghost.service"]["missed"], 5)

    def test_missed_resets_when_seen_again(self):
        act = self.chain({}, self.ghost_prev(), 5)
        act, _ = self.tick({"k": node(unit="ghost.service",
                                      state="active")},
                           {"actuation": act, "actions": []},
                           mode="recommend")
        self.assertEqual(act["units"]["ghost.service"]["missed"], 0)

    def test_held_cleared_on_recovery(self):
        prev = {"actuation": {"mode": "recommend", "units": {
            "jev-x.service": {"fail_ticks": 3,
                              "held": {"gate": "not-allowlisted",
                                       "ts": iso_ago(60)}}}},
                "actions": []}
        act, _ = self.tick({"k": node(state="active")}, prev,
                           mode="recommend")
        self.assertNotIn("held", act["units"]["jev-x.service"])


if __name__ == "__main__":
    unittest.main()
