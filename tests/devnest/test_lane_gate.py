"""Tests for the graduated OpenCode routing gate
(scripts/devnest/lane_gate.py). Synthetic probe/stage state — no
network, no real state dir writes.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/devnest/lane_gate.py"

spec = importlib.util.spec_from_file_location("lane_gate", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["lane_gate"] = mod
spec.loader.exec_module(mod)

PROBE_OK = {"host": "tony-macbook", "at": "x", "simulated": None,
            "tools": {"opencode": True, "devin": True, "git": True,
                      "python3": True},
            "net": {"litellm": True, "litellm_authed": True,
                    "ollama_local": False, "ollama_idc02": False,
                    "ollama_idc03": False, "tailnet": True, "wan": True,
                    "devin_cloud": True},
            "secrets": {"litellm_keys_env": True},
            "models": {}}
PROBE_DEAD = json.loads(json.dumps(PROBE_OK))
PROBE_DEAD["net"] = {k: False for k in PROBE_DEAD["net"]}


def mk_env(**kw):
    env = {
        "id": "j-test", "card": "c-test", "task_class": "shadow_replay",
        "stage": "S0", "target_host": "tony-macbook",
        "executor": "opencode", "fixture": "host-health",
        "model": "litellm/gemini-3.5-flash-lite", "provider": "litellm",
        "mcp_allowlist": [], "allowed_paths": ["evals/shadow/task/"],
        "artifact": {"path": "evals/shadow/task/artifacts/health.json",
                     "schema": "task.yaml#contract"},
        "verifier": {"type": "held_out_py",
                     "ref": "evals/shadow/fixtures/host-health/verify.py"},
        "escalation": {"on_fail": "manual", "max_retries": 1},
        "rollback": {"kind": "worktree-drop", "ref": "shadow wt"},
        "heartbeat": {"required": False},
    }
    env.update(kw)
    return env


def stage_state(stage="S0", done=0):
    return {"current_stage": stage,
            "history": [], "jobs_completed": {stage: done},
            "review_due": None}


def admit(env, stage="S0", probe=None, host="tony-macbook", inflight=0,
          done=0):
    return mod.admit(env, probe=probe if probe is not None else PROBE_OK,
                     host=host, stage_state=stage_state(stage, done),
                     inflight=inflight)


class Lint(unittest.TestCase):
    def test_valid_envelope(self):
        self.assertEqual(mod.lint_envelope(mk_env()), [])

    def test_missing_required_fields(self):
        env = mk_env()
        for k in ("card", "verifier", "rollback"):
            del env[k]
        errs = mod.lint_envelope(env)
        for k in ("card", "verifier", "rollback"):
            self.assertIn(f"missing_envelope_field:{k}", errs)

    def test_nested_section_fields_required(self):
        env = mk_env(artifact={"path": "x"})  # schema missing
        self.assertIn("missing_envelope_field:artifact.schema",
                      mod.lint_envelope(env))

    def test_bad_class_and_stage(self):
        errs = mod.lint_envelope(mk_env(task_class="bogus", stage="S9"))
        self.assertTrue(any(e.startswith("bad_value:task_class")
                            for e in errs))
        self.assertTrue(any(e.startswith("bad_value:stage")
                            for e in errs))


class Admit(unittest.TestCase):
    def test_clean_s0_envelope_admits(self):
        d = admit(mk_env())
        self.assertTrue(d["admit"], d["reasons"])

    def test_kill_switch_env_denies(self):
        os.environ["OPENCODE_LANE_KILL"] = "test"
        try:
            d = admit(mk_env())
        finally:
            del os.environ["OPENCODE_LANE_KILL"]
        self.assertFalse(d["admit"])
        self.assertTrue(any(r.startswith("kill_switch")
                            for r in d["reasons"]))

    def test_wrong_stage_denied(self):
        d = admit(mk_env(stage="S3"), stage="S0")
        self.assertFalse(d["admit"])
        self.assertTrue(any(r.startswith("wrong_stage")
                            for r in d["reasons"]))

    def test_production_class_never_admitted(self):
        for s in mod.STAGE_ORDER:
            d = admit(mk_env(task_class="production", stage=s), stage=s)
            self.assertFalse(d["admit"])
            self.assertIn(f"denied_class:production", d["reasons"])

    def test_class_not_in_stage(self):
        d = admit(mk_env(task_class="branch_code", stage="S1"),
                  stage="S1")
        self.assertFalse(d["admit"])
        self.assertTrue(any(r.startswith("class_not_in_stage")
                            for r in d["reasons"]))

    def test_wrong_host(self):
        d = admit(mk_env(), host="idc02")
        self.assertFalse(d["admit"])
        self.assertTrue(any(r.startswith("wrong_host")
                            for r in d["reasons"]))

    def test_missing_verifier(self):
        d = admit(mk_env(verifier={"type": "held_out_py",
                                   "ref": "no/such/verify.py"}))
        self.assertFalse(d["admit"])
        self.assertTrue(any(r.startswith("missing_verifier")
                            for r in d["reasons"]))

    def test_denied_tool(self):
        d = admit(mk_env(mcp_allowlist=["mcp_raw"]))
        self.assertFalse(d["admit"])
        self.assertIn("denied_tool:mcp_raw", d["reasons"])

    def test_readonly_mcp_denied_at_s0(self):
        # S0 permits NO mcp tools at all — fixtures are self-contained
        d = admit(mk_env(mcp_allowlist=["mcp_health"]))
        self.assertFalse(d["admit"])
        self.assertIn("denied_tool:mcp_health", d["reasons"])

    def test_readonly_mcp_ok_at_s1(self):
        env = mk_env(task_class="read_only", stage="S1",
                     mcp_allowlist=["mcp_health", "mcp_debug"])
        d = admit(env, stage="S1")
        self.assertFalse(any(r.startswith("denied_tool")
                             for r in d["reasons"]))

    def test_denied_path(self):
        d = admit(mk_env(allowed_paths=["/etc/", "evals/shadow/task/"]))
        self.assertFalse(d["admit"])
        self.assertIn("denied_path:/etc/", d["reasons"])

    def test_stale_heartbeat(self):
        env = mk_env(id="nope-never-ran-zzz",
                     heartbeat={"required": True, "stale_s": 5})
        d = admit(env)
        self.assertFalse(d["admit"])
        self.assertIn("stale_heartbeat", d["reasons"])

    def test_failed_provider(self):
        d = admit(mk_env(), probe=PROBE_DEAD)
        self.assertFalse(d["admit"])
        self.assertIn("failed_provider:litellm", d["reasons"])

    def test_concurrency_cap(self):
        d = admit(mk_env(), inflight=1)  # S0 cap is 1
        self.assertFalse(d["admit"])
        self.assertTrue(any(r.startswith("concurrency_cap")
                            for r in d["reasons"]))

    def test_s1_requires_opencode_lanes_env(self):
        env = mk_env(task_class="report", stage="S1")
        d = admit(env, stage="S1")
        self.assertIn("env_gate:OPENCODE_LANES!=1", d["reasons"])
        d2 = mod.admit(env, probe=PROBE_OK, host="tony-macbook",
                       stage_state=stage_state("S1"), inflight=0,
                       env_get=lambda k, d=None:
                       "1" if k == "OPENCODE_LANES" else d)
        self.assertFalse(any(r.startswith("env_gate")
                             for r in d2["reasons"]))

    def test_quota_exceeded(self):
        env = mk_env(task_class="report", stage="S1")
        d = mod.admit(env, probe=PROBE_OK, host="tony-macbook",
                      stage_state=stage_state("S1", done=3), inflight=0,
                      env_get=lambda k, d=None:
                      "1" if k == "OPENCODE_LANES" else d)
        self.assertTrue(any(r.startswith("quota_exceeded")
                            for r in d["reasons"]))

    def test_s5_branch_code_needs_strong_model(self):
        env = mk_env(task_class="branch_code", stage="S5",
                     model="litellm/gemini-3.5-flash-lite",
                     rollback={"kind": "git-revert", "ref": "HEAD"},
                     verifier={"type": "independent_devin",
                               "ref": "devin-review"},
                     allowed_paths=["scripts/"])
        d = admit(env, stage="S5")
        self.assertIn("weak_model:litellm/gemini-3.5-flash-lite",
                      d["reasons"])
        env["model"] = "litellm/claude-fable-5.1"
        d2 = mod.admit(env, probe=PROBE_OK, host="tony-macbook",
                       stage_state=stage_state("S5"), inflight=0,
                       env_get=lambda k, d=None:
                       "1" if k == "OPENCODE_LANES" else d)
        self.assertTrue(d2["admit"], d2["reasons"])

    def test_branch_code_needs_rollback(self):
        env = mk_env(task_class="branch_code", stage="S5",
                     model="litellm/claude-fable-5.1",
                     rollback={"kind": "none", "ref": ""},
                     verifier={"type": "independent_devin",
                               "ref": "devin-review"})
        d = admit(env, stage="S5")
        self.assertTrue(any(r.startswith("missing_rollback")
                            for r in d["reasons"]))

    def test_lint_failure_short_circuits(self):
        d = admit({"id": "x"})
        self.assertFalse(d["admit"])
        self.assertTrue(any(r.startswith("missing_envelope_field")
                            for r in d["reasons"]))


class ReviewAndMetrics(unittest.TestCase):
    def _rec(self, ok=True, fail=None, **kw):
        m = {"job_id": "j", "stage": "S0", "executor": "opencode",
             "verifier_pass": ok,
             "artifact_landed": ok, "failure_reason": fail,
             "input_tokens": 100, "output_tokens": 50,
             "cache_read_tokens": 0, "cache_write_tokens": 0,
             "combined_cost_usd": 0.01, "wall_s": 10.0, "queue_s": 0.0,
             "retries": 0, "tool_denials": 0, "human_minutes": 0,
             "escalated": False}
        m.update(kw)
        return m

    def test_promote_when_gate_met(self):
        recs = [self._rec() for _ in range(5)]
        r = mod.review(stage_state("S0"), recs)
        self.assertEqual(r["decision"], "promote")
        self.assertEqual(r["promote_to"], "S1")

    def test_hold_below_min_jobs(self):
        r = mod.review(stage_state("S0"), [self._rec()])
        self.assertEqual(r["decision"], "hold")
        self.assertTrue(any("min" in x or "<" in x
                            for x in r["reasons"]))

    def test_hold_below_verified_rate(self):
        recs = [self._rec() for _ in range(4)] + \
               [self._rec(ok=False, fail="unverified_exit")
                for _ in range(4)]
        r = mod.review(stage_state("S0"), recs)
        self.assertEqual(r["decision"], "hold")

    def test_rollback_on_safety_failure(self):
        recs = [self._rec() for _ in range(5)]
        recs.append(self._rec(ok=False, fail="tool_denial:mcp_raw",
                              tool_denials=1))
        r = mod.review(stage_state("S0"), recs)
        self.assertEqual(r["decision"], "rollback")
        self.assertEqual(r["rollback_to"], "S0")  # already floor

    def test_rollback_target_from_s3(self):
        recs = [self._rec(stage="S3", ok=False,
                          fail="scope_violation")]
        r = mod.review(stage_state("S3"), recs)
        self.assertEqual(r["rollback_to"], "S2")

    def test_terminal_stage_holds(self):
        recs = [self._rec(stage="S5") for _ in range(9)]
        r = mod.review(stage_state("S5"), recs)
        self.assertEqual(r["decision"], "hold")
        self.assertIsNone(r["promote_to"])

    def test_review_ignores_baseline_arms(self):
        # 5 passing l0 baselines + 1 failing opencode job -> lane rate
        # is 0/1, not 5/6 — baselines must not inflate the gate
        recs = [self._rec(executor="l0") for _ in range(5)]
        recs.append(self._rec(ok=False, fail="unverified_exit"))
        r = mod.review(stage_state("S0"), recs)
        self.assertEqual(r["aggregate"]["jobs"], 1)
        self.assertEqual(r["decision"], "hold")

    def test_aggregate_fields(self):
        recs = [self._rec(wall_s=10), self._rec(wall_s=20),
                self._rec(ok=False, fail="missing_artifact",
                          wall_s=30, retries=2)]
        a = mod.aggregate(recs)
        self.assertEqual(a["jobs"], 3)
        self.assertEqual(a["verified"], 2)
        self.assertAlmostEqual(a["verified_success_rate"], 2 / 3,
                               places=2)
        self.assertEqual(a["retries_total"], 2)
        self.assertEqual(a["failure_reasons"],
                         {"missing_artifact": 1})
        self.assertEqual(a["wall_s_median"], 20)
        for k in ("tokens_per_verified_job", "cost_per_verified_job_usd",
                  "wall_s_p95", "queue_s_p95", "human_minutes_total",
                  "devin_tokens_displaced", "escalations", "by_stage"):
            self.assertIn(k, a)

    def test_devin_tokens_displaced(self):
        recs = [self._rec(devin_equiv_tokens=50000)]
        a = mod.aggregate(recs)
        # verified job used 150 in+out tokens vs 50k devin-equivalent
        self.assertEqual(a["devin_tokens_displaced"], 49850)


class EnvelopeLibrary(unittest.TestCase):
    def test_five_s0_envelopes_parse_and_lint(self):
        jobs = sorted((REPO / "evals/opencode-lane/jobs").glob("s0-*.yaml"))
        self.assertEqual(len(jobs), 5)
        for j in jobs:
            env = mod.load_envelope(j)
            self.assertEqual(mod.lint_envelope(env), [], j.name)
            self.assertEqual(env["stage"], "S0")
            self.assertEqual(env["task_class"], "shadow_replay")

    def test_yaml_fallback_parser(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "e.yaml"
            p.write_text(
                "id: t\ncard: c\ntask_class: shadow_replay\nstage: S0\n"
                "target_host: h\nexecutor: opencode\nmodel: m\n"
                "provider: litellm\n"
                "mcp_allowlist: [mcp_health, mcp_debug]\n"
                "allowed_paths:\n  - evals/shadow/task/\n"
                "artifact:\n  path: a.json\n  schema: s\n"
                "verifier:\n  type: held_out_py\n  ref: v.py\n"
                "escalation:\n  on_fail: manual\n  max_retries: 1\n"
                "rollback:\n  kind: worktree-drop\n  ref: wt\n"
                "heartbeat:\n  required: false\n")
                # exercise the no-pyyaml fallback explicitly
            sys.modules.pop("yaml", None)
            env = mod._load_yaml_min(p)
        self.assertEqual(env["id"], "t")
        self.assertEqual(env["mcp_allowlist"],
                         ["mcp_health", "mcp_debug"])
        self.assertEqual(env["allowed_paths"], ["evals/shadow/task/"])
        self.assertEqual(env["artifact"]["path"], "a.json")
        self.assertEqual(env["verifier"]["type"], "held_out_py")
        self.assertFalse(env["heartbeat"]["required"])
        self.assertEqual(env["escalation"]["max_retries"], 1)


if __name__ == "__main__":
    unittest.main()
