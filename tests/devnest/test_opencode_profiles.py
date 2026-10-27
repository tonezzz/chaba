"""Tests for task-scoped OpenCode agent profiles
(scripts/devnest/opencode_profiles.py) — card
opencode-task-agent-profiles. Synthetic envelopes/profiles only; no
network, no real opencode invocations, no host state writes.
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
SCRIPT = REPO / "scripts/devnest/opencode_profiles.py"

# never let a test touch the host's real lane state dir
os.environ["OPENCODE_LANE_STATE"] = tempfile.mkdtemp(
    prefix="oc-profiles-test-state-")

spec = importlib.util.spec_from_file_location("opencode_profiles", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["opencode_profiles"] = mod
spec.loader.exec_module(mod)
lane_gate = mod.lane_gate

PROBE_OK = {"host": "idc02", "at": "x", "simulated": None,
            "tools": {"opencode": True, "devin": True, "git": True,
                      "python3": True},
            "net": {"litellm": True, "litellm_authed": True,
                    "tailnet": True, "wan": True},
            "secrets": {"litellm_keys_env": True}, "models": {}}


def mk_env(profile="ops-readonly", **kw):
    """Envelope that is a consistent narrowing of the named profile —
    schema/verifier/model defaults come FROM the profile so the pair
    passes check_envelope; kw can then dirty individual fields."""
    prof = mod.load_profile(profile)
    env = {
        "id": "j-test", "card": "c-test", "task_class": "read_only",
        "stage": "S1", "target_host": "idc02", "executor": "opencode",
        "profile": profile,
        "model": (prof.get("model") or {}).get("default")
            or "litellm/gemini-3.5-flash-lite",
        "provider": (prof.get("providers") or ["litellm"])[0],
        "unattended": True,
        "mcp_allowlist": [],
        "allowed_paths": ["evals/opencode-lane/out/"],
        "artifact": {"path": "evals/opencode-lane/out/j.json",
                     "schema": (prof.get("artifact") or {})
                     .get("schema", "")},
        "verifier": dict(prof.get("verifier") or
                         {"type": "held_out_py", "ref": "x"}),
        "escalation": {"on_fail": "manual", "max_retries": 0},
        "rollback": {"kind": (prof.get("rollback") or {})
                     .get("kind", "none")},
        "heartbeat": {"required": False},
    }
    if profile == "branch-code":
        env.update({"task_class": "branch_code", "stage": "S5",
                    "allowed_paths": ["scripts/"],
                    "escalation": {"on_fail": "manual",
                                   "max_retries": 0}})
    env.update(kw)
    return env


class LintProfiles(unittest.TestCase):
    def test_all_committed_profiles_lint_clean(self):
        pids = mod.list_profiles()
        self.assertEqual(sorted(pids),
                         ["branch-code", "ops-readonly",
                          "ssot-research", "storage-dryrun"])
        for pid in pids:
            self.assertEqual(mod.lint_profile(mod.load_profile(pid)),
                             [], pid)

    def test_branch_code_defined_but_disabled(self):
        p = mod.load_profile("branch-code")
        self.assertEqual(p["status"], "disabled")
        self.assertFalse(p["unattended"])
        self.assertEqual(p["model"]["tier"], "strong")
        self.assertEqual(p["verifier"]["type"], "independent_devin")
        self.assertTrue(p["verifier"]["require_tests"])
        self.assertTrue(p["verifier"]["require_review"])
        self.assertEqual(p["rollback"]["kind"], "worktree-drop")

    def test_mcp_overlap_rejected(self):
        p = mod.load_profile("ops-readonly")
        p["mcp"] = {"allowed": ["mcp_health"],
                    "denied": ["mcp_health"]}
        self.assertTrue(any("overlap" in e
                            for e in mod.lint_profile(p)))

    def test_mcp_outside_lane_set_rejected(self):
        p = mod.load_profile("ops-readonly")
        p["mcp"]["allowed"] = ["mcp_health", "mcp_raw"]
        self.assertTrue(any("outside_lane_set" in e
                            for e in mod.lint_profile(p)))

    def test_write_tools_require_scoped_paths(self):
        p = mod.load_profile("ops-readonly")
        p["tools"]["write"] = True
        self.assertTrue(any("writes_unscoped" in e
                            for e in mod.lint_profile(p)))
        p["allowed_paths"] = ["evals/opencode-lane/out/"]
        self.assertFalse(any("writes_unscoped" in e
                             for e in mod.lint_profile(p)))

    def test_weak_strong_default_rejected(self):
        p = mod.load_profile("ops-readonly")
        p["model"] = {"tier": "strong",
                      "default": "litellm/gemini-3.5-flash-lite"}
        self.assertTrue(any("weak_model_default" in e
                            for e in mod.lint_profile(p)))

    def test_artifact_dir_outside_roots_rejected(self):
        p = mod.load_profile("ops-readonly")
        p["artifact"]["dirs"] = ["/etc/"]
        self.assertTrue(any("artifact_dir_outside_roots" in e
                            for e in mod.lint_profile(p)))

    def test_missing_required_fields(self):
        for k in ("mcp", "verifier", "rollback", "target_host",
                  "artifact", "rails"):
            p = mod.load_profile("ops-readonly")
            del p[k]
            self.assertIn(f"missing_profile_field:{k}",
                          mod.lint_profile(p), k)


class CheckEnvelope(unittest.TestCase):
    def test_clean_envelope_passes(self):
        for pid in ("ops-readonly", "ssot-research", "storage-dryrun"):
            prof = mod.load_profile(pid)
            self.assertEqual(
                mod.check_envelope(mk_env(pid), prof), [], pid)

    def test_denied_tool(self):
        prof = mod.load_profile("ops-readonly")
        d = mod.check_envelope(mk_env(mcp_allowlist=["mcp_raw"]), prof)
        self.assertIn("profile_denied_tool:mcp_raw", d)

    def test_tool_outside_profile_ceiling(self):
        # mcp_mddb_doc is a lane-read-only tool but NOT in
        # storage-dryrun's ceiling — widening denied
        prof = mod.load_profile("storage-dryrun")
        d = mod.check_envelope(
            mk_env("storage-dryrun", mcp_allowlist=["mcp_mddb_doc"]),
            prof)
        self.assertIn("profile_denied_tool:mcp_mddb_doc", d)

    def test_denied_path(self):
        prof = mod.load_profile("ops-readonly")
        d = mod.check_envelope(mk_env(allowed_paths=["/etc/"]), prof)
        self.assertIn("profile_denied_path:/etc/", d)

    def test_denied_artifact_path(self):
        prof = mod.load_profile("ops-readonly")
        env = mk_env()
        env["artifact"] = {"path": "docs/evil.json",
                           "schema": env["artifact"]["schema"]}
        d = mod.check_envelope(env, prof)
        self.assertIn("profile_denied_artifact:docs/evil.json", d)

    def test_wrong_stage_and_class(self):
        prof = mod.load_profile("ops-readonly")
        d = mod.check_envelope(mk_env(stage="S4"), prof)
        self.assertIn("profile_wrong_stage:S4", d)
        d = mod.check_envelope(mk_env(task_class="branch_code"), prof)
        self.assertIn("profile_wrong_class:branch_code", d)

    def test_host_restriction(self):
        prof = mod.load_profile("ops-readonly")
        prof["target_host"] = {"required": True,
                               "allowed": ["tony-macbook"]}
        d = mod.check_envelope(mk_env(), prof)
        self.assertIn("profile_wrong_host:idc02", d)
        d = mod.check_envelope(mk_env(target_host="tony-macbook"), prof)
        self.assertNotIn("profile_wrong_host:tony-macbook", d)

    def test_missing_target_when_required(self):
        prof = mod.load_profile("ops-readonly")
        env = mk_env()
        del env["target_host"]
        self.assertIn("profile_missing_target",
                      mod.check_envelope(env, prof))

    def test_model_ceiling(self):
        prof = mod.load_profile("ops-readonly")
        d = mod.check_envelope(
            mk_env(model="litellm/claude-fable-5.1"), prof)
        self.assertIn("profile_denied_model:litellm/claude-fable-5.1",
                      d)

    def test_branch_code_strong_model_floor(self):
        # even if branch-code were enabled, a cheap model is denied
        prof = mod.load_profile("branch-code")
        prof["status"] = "enabled"
        prof["unattended"] = True
        env = mk_env("branch-code",
                     model="litellm/gemini-3.5-flash-lite")
        d = mod.check_envelope(env, prof)
        self.assertIn("profile_weak_model:"
                      "litellm/gemini-3.5-flash-lite", d)
        env["model"] = "litellm/claude-fable-5.1"
        self.assertFalse(any("profile_weak_model" in r
                             for r in mod.check_envelope(env, prof)))

    def test_weak_verifier_floor(self):
        # branch-code floor is independent_devin — held_out_py is weak
        prof = mod.load_profile("branch-code")
        prof["status"] = "enabled"
        prof["unattended"] = True
        env = mk_env("branch-code")
        env["verifier"] = {"type": "held_out_py", "ref": "x"}
        self.assertIn("profile_weak_verifier:held_out_py",
                      mod.check_envelope(env, prof))

    def test_schema_mismatch(self):
        prof = mod.load_profile("ops-readonly")
        env = mk_env()
        env["artifact"]["schema"] = "other/schema.yaml#x"
        d = mod.check_envelope(env, prof)
        self.assertTrue(any(r.startswith("profile_schema_mismatch")
                            for r in d))

    def test_escalation_and_retries_caps(self):
        prof = mod.load_profile("storage-dryrun")   # max_retries: 0
        env = mk_env("storage-dryrun",
                     escalation={"on_fail": "retry_then_manual",
                                 "max_retries": 3})
        d = mod.check_envelope(env, prof)
        self.assertTrue(any(r.startswith("profile_retries") for r in d))
        # hold is a declared allowed_on_fail for this profile
        env["escalation"] = {"on_fail": "hold", "max_retries": 0}
        d = mod.check_envelope(env, prof)
        self.assertFalse(any(r.startswith("profile_denied_escalation")
                             for r in d))
        env["escalation"] = {"on_fail": "devin", "max_retries": 0}
        d = mod.check_envelope(env, prof)
        self.assertFalse(any(r.startswith("profile_denied_escalation")
                             for r in d))

    def test_rollback_floor(self):
        prof = mod.load_profile("branch-code")
        prof["status"] = "enabled"
        prof["unattended"] = True
        env = mk_env("branch-code", rollback={"kind": "none"})
        self.assertIn("profile_rollback:none",
                      mod.check_envelope(env, prof))
        env["rollback"] = {"kind": "git-revert"}
        self.assertFalse(any(r.startswith("profile_rollback")
                             for r in mod.check_envelope(env, prof)))
        env["rollback"] = {"kind": "file-restore"}
        self.assertIn("profile_rollback:file-restore",
                      mod.check_envelope(env, prof))

    def test_disabled_profile_denied(self):
        prof = mod.load_profile("branch-code")
        d = mod.check_envelope(mk_env("branch-code"), prof)
        self.assertIn("profile_disabled:branch-code", d)
        self.assertIn("profile_not_unattended:branch-code", d)


class Render(unittest.TestCase):
    def test_render_disables_builtin_agents(self):
        prof = mod.load_profile("ops-readonly")
        cfg = mod.render_config(mk_env(), prof)
        for a in ("build", "plan", "general"):
            self.assertTrue(cfg["agent"][a]["disable"], a)
        self.assertIn("ops-readonly", cfg["agent"])

    def test_rendered_agent_scoped(self):
        prof = mod.load_profile("ops-readonly")
        cfg = mod.render_config(mk_env(), prof)
        ag = cfg["agent"]["ops-readonly"]
        self.assertEqual(ag["mode"], "primary")
        self.assertFalse(ag["tools"]["write"])
        self.assertFalse(ag["tools"]["edit"])
        self.assertTrue(ag["tools"]["read"])
        self.assertEqual(ag["permission"]["edit"], "deny")
        self.assertEqual(ag["permission"]["bash"]["*"], "deny")
        self.assertEqual(ag["permission"]["bash"]["df *"], "allow")
        self.assertIn("ops-readonly profile agent", ag["prompt"])
        # agent prompt is rails-only — task text is the run message
        self.assertNotIn("{{TASK}}", ag["prompt"])

    def test_agent_name_slug(self):
        self.assertEqual(mod.agent_name("ops-readonly"), "ops-readonly")

    def test_ssot_research_has_no_bash(self):
        prof = mod.load_profile("ssot-research")
        cfg = mod.render_config(mk_env("ssot-research"), prof)
        ag = cfg["agent"]["ssot-research"]
        self.assertFalse(ag["tools"]["bash"])
        self.assertEqual(ag["permission"]["bash"], "deny")

    def test_mcp_absent_without_proxy(self):
        # no mcp-allowlist proxy on test host -> zero MCP surface
        prof = mod.load_profile("ops-readonly")
        cfg = mod.render_config(mk_env(mcp_allowlist=["mcp_health"]),
                                prof)
        if not mod.proxy_available(prof):
            self.assertEqual(cfg["mcp"], {})

    def test_render_bundle_writes_files(self):
        prof = mod.load_profile("ops-readonly")
        with tempfile.TemporaryDirectory() as td:
            man = mod.render_bundle(mk_env(), prof, Path(td))
            for f in ("opencode.json", "prompt.md", "manifest.json"):
                self.assertTrue((Path(td) / f).is_file(), f)
            cfg = json.loads((Path(td) / "opencode.json").read_text())
            self.assertTrue(cfg["agent"]["build"]["disable"])
            self.assertEqual(man["agent"], "ops-readonly")
            # prompt carries the task + lane rails
            prompt = (Path(td) / "prompt.md").read_text()
            self.assertIn("Lane rails", prompt)


class ArtifactExtraction(unittest.TestCase):
    def test_fenced_json(self):
        t = "noise\n```json\n{\"a\": 1}\n```\ndone"
        self.assertEqual(json.loads(mod.extract_artifact(t, "json")),
                         {"a": 1})

    def test_raw_last_object(self):
        t = "first {\"a\":1} then final {\"b\":2}"
        self.assertEqual(json.loads(mod.extract_artifact(t, "json")),
                         {"b": 2})

    def test_no_json_returns_none(self):
        self.assertIsNone(mod.extract_artifact("no json here", "json"))

    def test_markdown_passthrough(self):
        self.assertEqual(mod.extract_artifact("# rep", "markdown"),
                         "# rep")


class StoragePolicy(unittest.TestCase):
    def test_seeded_traps_all_refused(self):
        # every trap in the committed fixture input must classify to a
        # non-automatic action — this is the acceptance rule
        spec = json.loads((REPO / "evals/opencode-lane/profiles/"
                           "storage-dryrun/fixture/inputs/"
                           "storage-scan.json").read_text())
        prof = mod.load_profile("storage-dryrun")
        pol = prof["policy"]
        traps = [s for s in spec["proposals"] if "TRAP" in s["note"]]
        self.assertTrue(traps)
        for s in traps:
            r = mod.classify_candidate(s["path"], s["kind"], pol)
            self.assertNotEqual(r["action"], "automatic_ok",
                                f"{s['path']} must not be automatic")
            self.assertTrue(r["refused"], s["path"])

    def test_legit_kinds_allowed(self):
        prof = mod.load_profile("storage-dryrun")
        for path, kind in (("tests/__pycache__", "pycache"),
                           ("scripts/x.pyc", "pyc"),
                           ("tmp/junk.bin", "tmpfile")):
            r = mod.classify_candidate(path, kind,
                                       prof["policy"])
            self.assertEqual(r["action"], "automatic_ok",
                             f"{path} {kind}")

    def test_undeclared_kind_manual_review(self):
        prof = mod.load_profile("storage-dryrun")
        r = mod.classify_candidate("var/stuff.bin", "other",
                                   prof["policy"])
        self.assertEqual(r["action"], "manual_review")
        self.assertTrue(r["refused"])

    def test_auto_kind_under_protected_root_refused(self):
        prof = mod.load_profile("storage-dryrun")
        r = mod.classify_candidate(
            "evals/opencode-lane/profiles", "empty_dir",
            prof["policy"])
        self.assertEqual(r["action"], "never")
        self.assertTrue(r["refused"])


class EventAudit(unittest.TestCase):
    def _log(self, td, events):
        p = Path(td) / "events.jsonl"
        p.write_text("\n".join(json.dumps(e) for e in events))
        return p

    def test_denied_and_mutating_detected(self):
        prof = mod.load_profile("ops-readonly")
        ev = [
            {"part": {"type": "tool", "tool": "bash",
                      "state": {"status": "error",
                                "input": {"command": "rm -rf /tmp/x"},
                                "error": "The user has specified a "
                                         "rule which prevents"}}},
            {"part": {"type": "tool", "tool": "bash",
                      "state": {"status": "completed",
                                "input": {"command": "df -h /"}}}},
            {"part": {"type": "tool", "tool": "bash",
                      "state": {"status": "completed",
                                "input": {"command":
                                          "find . -name x -delete"}}}},
            {"part": {"type": "tool", "tool": "write",
                      "state": {"status": "error",
                                "input": {"filePath": "/tmp/w"},
                                "error": "denied by rule"}}},
            {"part": {"type": "step-finish",
                      "tokens": {"total": 10, "input": 8, "output": 2}}},
        ]
        with tempfile.TemporaryDirectory() as td:
            a = mod.audit_events(self._log(td, ev), mk_env(), prof)
        self.assertEqual(len(a["denials"]), 2)      # rm + write
        self.assertEqual(len(a["mutating_commands"]), 2)  # rm + -delete
        self.assertEqual(len(a["write_attempts"]), 1)
        self.assertEqual(a["tokens"]["input"], 8)

    def test_unlisted_mcp_call_flagged(self):
        prof = mod.load_profile("ops-readonly")
        ev = [{"part": {"type": "tool", "tool": "mcp_raw",
                        "state": {"status": "completed", "input": {}}}}]
        with tempfile.TemporaryDirectory() as td:
            a = mod.audit_events(self._log(td, ev), mk_env(), prof)
        self.assertIn("mcp_unlisted:mcp_raw", a["denials"])

    def test_verifier_peek_flagged(self):
        prof = mod.load_profile("ops-readonly")
        ev = [{"part": {"type": "tool", "tool": "read",
                        "state": {"status": "completed",
                                  "input": {"filePath":
                                            "evals/opencode-lane/"
                                            "profiles/x/fixture/"
                                            "verify.py"}}}}]
        with tempfile.TemporaryDirectory() as td:
            a = mod.audit_events(self._log(td, ev), mk_env(), prof)
        self.assertTrue(a["verifier_peeks"])

    def test_final_text_last_text_part(self):
        ev = [{"part": {"type": "text", "text": "first"}},
              {"part": {"type": "tool", "tool": "bash",
                        "state": {"status": "completed",
                                  "input": {"command": "df"}}}},
              {"part": {"type": "text", "text": "{\"done\":1}"}}]
        with tempfile.TemporaryDirectory() as td:
            p = self._log(td, ev)
            self.assertEqual(mod.final_text(p), "{\"done\":1}")


class AdmitIntegration(unittest.TestCase):
    """lane_gate.admit profile-aware deny reasons — the generic build
    agent stays out of unattended routing."""

    def _admit(self, env, stage="S1"):
        st = {"current_stage": stage, "history": [],
              "jobs_completed": {}, "review_due": None}
        return lane_gate.admit(
            env, probe=PROBE_OK, host="idc02", stage_state=st,
            inflight=0,
            env_get=lambda k, d=None:
            "1" if k == "OPENCODE_LANES" else d)

    def test_missing_profile_denied(self):
        env = mk_env()
        del env["profile"]
        d = self._admit(env)
        self.assertFalse(d["admit"])
        self.assertTrue(any(r.startswith("missing_profile")
                            for r in d["reasons"]))

    def test_unknown_profile_denied(self):
        env = mk_env()
        env["profile"] = "no-such-prof"
        d = self._admit(env)
        self.assertTrue(any(r.startswith("unknown_profile")
                            for r in d["reasons"]))

    def test_disabled_profile_denied(self):
        d = self._admit(mk_env("branch-code"))
        self.assertTrue(any(r.startswith("profile_disabled")
                            for r in d["reasons"]))
        self.assertTrue(any(r.startswith("profile_not_unattended")
                            for r in d["reasons"]))

    def test_shadow_replay_needs_no_profile(self):
        env = mk_env(task_class="shadow_replay", stage="S0",
                     fixture="host-health",
                     allowed_paths=["evals/shadow/task/"],
                     verifier={"type": "held_out_py",
                               "ref": "evals/shadow/fixtures/"
                                      "host-health/verify.py"},
                     rollback={"kind": "worktree-drop", "ref": "x"})
        del env["profile"]
        d = self._admit(env, stage="S0")
        self.assertFalse(any(r.startswith("missing_profile")
                             for r in d["reasons"]))
        self.assertTrue(d["admit"], d["reasons"])

    def test_enabled_profile_admits_at_s1(self):
        d = self._admit(mk_env())
        self.assertTrue(d["admit"], d["reasons"])

    def test_heartbeat_required_envelope(self):
        env = mk_env(heartbeat={"required": True, "stale_s": 5})
        d = self._admit(env)
        self.assertIn("stale_heartbeat", d["reasons"])


class RunPreflight(unittest.TestCase):
    def test_lint_failure_short_circuits(self):
        r = mod.run_preflight({"id": "x"})
        self.assertFalse(r["admit"])
        self.assertTrue(any("missing_envelope_field" in x
                            for x in r["reasons"]))

    def test_profile_check_aggregates_with_lane(self):
        env = mk_env(mcp_allowlist=["mcp_raw"])
        r = mod.run_preflight(env)
        self.assertFalse(r["admit"])
        self.assertIn("profile_denied_tool:mcp_raw", r["reasons"])

    def test_missing_profile_preflight(self):
        env = mk_env()
        del env["profile"]
        r = mod.run_preflight(env)
        self.assertFalse(r["admit"])
        self.assertIn("missing_profile", r["reasons"])


class JobLibrary(unittest.TestCase):
    def test_profile_envelopes_parse_and_lint(self):
        jobs = sorted((REPO / "evals/opencode-lane/jobs")
                      .glob("p*.yaml"))
        self.assertEqual(len(jobs), 4)
        for j in jobs:
            env = lane_gate.load_envelope(j)
            self.assertEqual(lane_gate.lint_envelope(env), [], j.name)
            self.assertIn("profile", env)

    def test_enabled_job_envelopes_consistent(self):
        for pid in ("ops-readonly", "ssot-research", "storage-dryrun"):
            j = REPO / "evals/opencode-lane/jobs" / \
                f"p1-{pid}-idc02.yaml"
            env = lane_gate.load_envelope(j)
            prof = mod.load_profile(pid)
            self.assertEqual(mod.check_envelope(env, prof), [], j.name)

    def test_branch_code_envelope_denied_by_profile(self):
        j = REPO / "evals/opencode-lane/jobs" / \
            "p5-branch-code-disabled.yaml"
        env = lane_gate.load_envelope(j)
        prof = mod.load_profile("branch-code")
        d = mod.check_envelope(env, prof)
        self.assertIn("profile_disabled:branch-code", d)
        self.assertIn("profile_not_unattended:branch-code", d)


if __name__ == "__main__":
    unittest.main()
