"""Tests for waiting_cards (scripts/board/waiting_cards.py — KNB-0928).

Covers the hands-off waiting-card gate: eligibility requirements
(action.type/target_host/autonomy/artifact/verifier/no-open-requests/
recoverability), the R0-R4 recoverability classes with the R3/R4
never-autonomous floor, preflight checks (kill switch, deploy lock,
disk headroom, queue capacity, R2 backup freshness, stale heartbeat),
and the lifecycle publish helper's never-raise contract.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "waiting_cards", REPO / "scripts" / "board" / "waiting_cards.py")
wc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wc)


def _card(**kw):
    c = {
        "id": "test-card",
        "column": "backlog",
        "autonomy": "t2",
        "recoverability": "R0",
        "auto_done_when": ["verified_true:"],
        "action": {"type": "script", "host": "idc03",
                   "artifact": "comms result", "verifier": "exit=0"},
    }
    c.update(kw)
    return c


def _env(**kw):
    env = {"kill_switch": False, "deploy_lock": False,
           "disk_free_mb": 100000.0, "disk_min_mb": 2048.0,
           "claimed": 0, "cap": 3}
    env.update(kw)
    return env


class TestEligibility(unittest.TestCase):
    def test_fully_declared_card_is_eligible(self):
        v = wc.evaluate(_card(), env=_env())
        self.assertTrue(v["eligible"], v["reasons"])
        self.assertFalse(v["never"])
        self.assertEqual(v["recoverability"], "R0")

    def test_manual_type_has_no_executor(self):
        c = _card(action={"type": "manual", "host": "idc03"})
        v = wc.evaluate(c, env=_env())
        self.assertFalse(v["eligible"])
        self.assertTrue(any("action.type" in r for r in v["reasons"]))

    def test_missing_target_host_holds(self):
        c = _card(action={"type": "script",
                          "artifact": "x", "verifier": "y"})
        v = wc.evaluate(c, env=_env())
        self.assertFalse(v["eligible"])
        self.assertTrue(any("target_host" in r for r in v["reasons"]))

    def test_target_host_alias_accepted(self):
        c = _card(action={"type": "script", "target_host": "idc03",
                          "artifact": "x", "verifier": "y"})
        v = wc.evaluate(c, env=_env())
        self.assertTrue(v["eligible"], v["reasons"])

    def test_missing_artifact_or_verifier_holds(self):
        c = _card()
        c["action"] = {"type": "script", "host": "idc03"}
        c.pop("auto_done_when")
        v = wc.evaluate(c, env=_env())
        self.assertFalse(v["eligible"])
        self.assertTrue(any("artifact" in r for r in v["reasons"]))
        self.assertTrue(any("verifier" in r for r in v["reasons"]))

    def test_pipeline_goals_count_as_artifact_and_verifier(self):
        c = _card(action={"type": "script", "host": "idc03"},
                  pipeline={"goals": [{"id": "g1"}]})
        c.pop("auto_done_when")
        v = wc.evaluate(c, env=_env())
        self.assertTrue(v["eligible"], v["reasons"])

    def test_open_request_blocks(self):
        c = _card(requests=[{"ask": "which host?", "status": "open"}])
        v = wc.evaluate(c, env=_env())
        self.assertFalse(v["eligible"])
        self.assertTrue(any("open request" in r for r in v["reasons"]))

    def test_answered_request_does_not_block(self):
        c = _card(requests=[{"ask": "which host?", "status": "answered"}])
        v = wc.evaluate(c, env=_env())
        self.assertTrue(v["eligible"], v["reasons"])

    def test_unanswered_ask_blocks(self):
        c = _card(ask={"question": "ok?", "status": "open"})
        v = wc.evaluate(c, env=_env())
        self.assertFalse(v["eligible"])

    def test_autonomy_above_ceiling_holds(self):
        c = _card(autonomy="t4")
        v = wc.evaluate(c, env=_env())
        self.assertFalse(v["eligible"])
        self.assertTrue(any("max_autonomy" in r for r in v["reasons"]))

    def test_undeclared_recoverability_holds(self):
        c = _card()
        c.pop("recoverability")
        v = wc.evaluate(c, env=_env())
        self.assertFalse(v["eligible"])
        self.assertTrue(any("recoverability" in r for r in v["reasons"]))


class TestRecoverabilityFloor(unittest.TestCase):
    def test_r3_never_autonomous(self):
        v = wc.evaluate(_card(recoverability="R3"), env=_env())
        self.assertFalse(v["eligible"])
        self.assertTrue(v["never"])

    def test_r4_never_autonomous(self):
        v = wc.evaluate(_card(recoverability="R4"), env=_env())
        self.assertFalse(v["eligible"])
        self.assertTrue(v["never"])

    def test_r2_requires_backup_proof(self):
        c = _card(recoverability="R2")
        v = wc.evaluate(c, env=_env(backup_fresh=None))
        self.assertFalse(v["eligible"])
        self.assertTrue(any("backup" in r for r in v["reasons"]))
        v = wc.evaluate(c, env=_env(backup_fresh=True))
        self.assertTrue(v["eligible"], v["reasons"])
        v = wc.evaluate(c, env=_env(backup_fresh=False))
        self.assertFalse(v["eligible"])

    def test_action_level_recoverability_alias(self):
        c = _card()
        c.pop("recoverability")
        c["action"]["recoverability"] = "r1"
        v = wc.evaluate(c, env=_env())
        self.assertEqual(v["recoverability"], "R1")
        self.assertTrue(v["eligible"], v["reasons"])


class TestPreflight(unittest.TestCase):
    def test_kill_switch_fails(self):
        fails = wc.preflight(_card(), _env(kill_switch=True))
        self.assertTrue(any("kill switch" in f for f in fails))

    def test_deploy_lock_fails(self):
        fails = wc.preflight(_card(), _env(deploy_lock=True))
        self.assertTrue(any("deploy lock" in f for f in fails))

    def test_disk_floor_fails(self):
        fails = wc.preflight(_card(), _env(disk_free_mb=100.0))
        self.assertTrue(any("disk headroom" in f for f in fails))

    def test_queue_capacity_fails(self):
        fails = wc.preflight(_card(), _env(claimed=3, cap=3))
        self.assertTrue(any("capacity" in f for f in fails))

    def test_stale_heartbeat_fails(self):
        fails = wc.preflight(_card(), _env(heartbeat_age_s=900.0,
                                          heartbeat_max_s=300.0))
        self.assertTrue(any("heartbeat" in f for f in fails))

    def test_preflight_flows_into_verdict(self):
        v = wc.evaluate(_card(), env=_env(disk_free_mb=1.0))
        self.assertFalse(v["eligible"])
        self.assertTrue(any("disk" in r for r in v["reasons"]))


class TestPushProbe(unittest.TestCase):
    def test_dispatch_card_needs_push_credentials(self):
        c = _card(action={"type": "dispatch", "repo": "chaba",
                          "host": "idc03", "artifact": "x",
                          "verifier": "y"})
        v = wc.evaluate(c, env=_env(), push_probe=lambda r: False)
        self.assertFalse(v["eligible"])
        self.assertTrue(any("push" in r for r in v["reasons"]))
        v = wc.evaluate(c, env=_env(), push_probe=lambda r: True)
        self.assertTrue(v["eligible"], v["reasons"])

    def test_script_card_skips_push_check(self):
        v = wc.evaluate(_card(), env=_env(),
                        push_probe=lambda r: False)
        self.assertTrue(v["eligible"], v["reasons"])


class TestPublish(unittest.TestCase):
    def test_unreachable_api_never_raises(self):
        ok = wc.publish("http://127.0.0.1:1", "card-x", "milestone",
                        "t", "b", timeout=2)
        self.assertFalse(ok)

    def test_bad_kind_rejected(self):
        self.assertFalse(wc.publish("http://127.0.0.1:1", "c", "bogus",
                                    "title"))


if __name__ == "__main__":
    unittest.main()
