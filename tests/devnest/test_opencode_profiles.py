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
from types import SimpleNamespace
from unittest import mock

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


class IndependentReview(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.old_state = os.environ["OPENCODE_LANE_STATE"]
        os.environ["OPENCODE_LANE_STATE"] = str(self.root / "state")
        self.repo_patch = mock.patch.object(mod, "REPO", self.root)
        self.repo_patch.start()
        self.gate_repo_patch = mock.patch.object(lane_gate, "REPO", self.root)
        self.gate_repo_patch.start()
        lane_gate.save_stage({"current_stage": "S2", "history": [], "jobs_completed": {"S2": 1}})
        self.rd = self.root / "run"
        self.rd.mkdir()
        self.env = mk_env(stage="S2", verifier={"type": "independent_devin", "ref": "verify.py"})
        self.dest = self.root / self.env["artifact"]["path"]
        self.dest.parent.mkdir(parents=True)
        self.dest.write_text('{"read_only":true}\n')
        for name, text in {"artifact.out": self.dest.read_text(), "events.jsonl": '{"sessionID":"producer-session"}\n',
                           "manifest.json": '{}', "prompt.md": 'read-only task', "verdict.json": '{"verdict":"skipped"}'}.items():
            (self.rd / name).write_text(text)
        self.metric = lane_gate.new_metric(self.env, "opencode")
        self.metric.update(artifact_landed=True, verifier_pass=False)

    def tearDown(self):
        self.repo_patch.stop()
        self.gate_repo_patch.stop()
        os.environ["OPENCODE_LANE_STATE"] = self.old_state
        self.td.cleanup()

    def prepare(self):
        pending = mod.prepare_independent_review(self.rd, self.env, self.metric)
        lane_gate.record_metric(self.metric)
        return pending

    def certificate(self, pending, **overrides):
        cert = {"schema": "independent_devin_attestation/1", "job": self.env["id"],
                "reviewer": "devin-independent", "reviewer_session": "review-session",
                "verdict": "pass", "evidence_sha256": pending["evidence_sha256"],
                "checks": {"admission_valid": True, "audit_clean_recomputed": True,
                           "artifact_matches_contract": True, "claims_verified": True},
                "findings": [], "at": "2026-11-09T04:00:00+00:00"}
        cert.update(overrides)
        path = self.root / "attestation.json"
        path.write_text(json.dumps(cert))
        return path

    def test_pending_then_review_appends_without_rewriting(self):
        pending = self.prepare()
        before = lane_gate.ledger_file().read_bytes()
        self.assertEqual(lane_gate.review()["aggregate"]["verified"], 0)
        self.assertIn("pending independent review", " ".join(lane_gate.review()["reasons"]))
        result = mod.finalize_independent_review(self.rd, self.certificate(pending))
        self.assertNotIn("error", result)
        self.assertTrue(lane_gate.ledger_file().read_bytes().startswith(before))
        self.assertEqual(lane_gate.review()["aggregate"]["jobs"], 1)
        self.assertEqual(lane_gate.review()["aggregate"]["verified"], 1)
        self.assertEqual(lane_gate.load_stage()["jobs_completed"], {"S2": 1})
        size = lane_gate.ledger_file().stat().st_size
        mod.finalize_independent_review(self.rd, self.certificate(pending))
        self.assertEqual(lane_gate.ledger_file().stat().st_size, size)

    def test_tamper_self_review_or_empty_checks_rejected(self):
        pending = self.prepare()
        for override in ({"reviewer_session": "producer-session"}, {"checks": {}},
                         {"job": "another"}, {"evidence_sha256": {}},
                         {"checks": {"admission_valid": "true"}}):
            self.assertIn("error", mod.finalize_independent_review(self.rd, self.certificate(pending, **override)))
        self.dest.write_text("tampered")
        self.assertIn("error", mod.finalize_independent_review(self.rd, self.certificate(pending)))
        self.assertEqual(lane_gate.review()["aggregate"]["verified"], 0)

    def test_failed_review_stays_failed(self):
        pending = self.prepare()
        result = mod.finalize_independent_review(self.rd, self.certificate(
            pending, verdict="fail", checks={"admission_valid": True, "audit_clean_recomputed": True,
                                            "artifact_matches_contract": False, "claims_verified": False}))
        self.assertNotIn("error", result)
        self.assertEqual(lane_gate.review()["aggregate"]["verified"], 0)
        self.assertIn("independent_review_failed", lane_gate.review()["aggregate"]["failure_reasons"])

    def test_review_survives_repository_relocation(self):
        import shutil
        pending = self.prepare()
        mod.finalize_independent_review(self.rd, self.certificate(pending))
        with tempfile.TemporaryDirectory() as td:
            relocated = Path(td) / "clone"
            shutil.copytree(self.root, relocated)
            with mock.patch.object(lane_gate, "REPO", relocated):
                self.assertEqual(lane_gate.review()["aggregate"]["verified"], 1)

    def test_metrics_count_execution_once_not_review_as_a_job(self):
        pending = self.prepare()
        mod.finalize_independent_review(self.rd, self.certificate(pending))
        result = lane_gate.metrics_summary(lane_gate.load_ledger())
        self.assertEqual(result["jobs"], 1)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(result["raw_ledger_records"], 2)

    def test_post_finalization_tamper_blocks_promotion(self):
        pending = self.prepare()
        mod.finalize_independent_review(self.rd, self.certificate(pending))
        self.dest.write_text("changed-after-review")
        result = lane_gate.review()
        self.assertEqual(result["decision"], "hold")
        self.assertIn("independent review invalid", " ".join(result["reasons"]))

    def test_duplicate_sources_or_finalizations_cannot_inflate_jobs(self):
        pending = self.prepare()
        mod.finalize_independent_review(self.rd, self.certificate(pending))
        lane_gate.record_metric(dict(self.metric))
        result = lane_gate.review()
        self.assertEqual(result["decision"], "hold")
        self.assertIn("independent review invalid", " ".join(result["reasons"]))

    def test_raw_finalized_claim_and_orphan_finalization_hold(self):
        for record in ({"executor": "opencode", "verification_status": "finalized",
                        "verifier_pass": True, "artifact_landed": True, "independent_review": {"fake": True}},
                       {"executor": "independent_reviewer", "finalizes": "unknown"}):
            result = lane_gate.review({"current_stage": "S2"}, [dict(record, stage="S2")])
            self.assertEqual(result["decision"], "hold")
            self.assertIn("independent review invalid", " ".join(result["reasons"]))

    def test_bad_finalization_does_not_hide_safety_rollback(self):
        pending = self.prepare()
        mod.finalize_independent_review(self.rd, self.certificate(pending))
        final = lane_gate.load_ledger()[-1]
        lane_gate.record_metric(dict(final))
        bad = lane_gate.new_metric(dict(self.env, id="unsafe"), "opencode")
        bad.update(failure_reason="tool_denial", tool_denials=1)
        lane_gate.record_metric(bad)
        self.assertEqual(lane_gate.review()["decision"], "rollback")

    def test_source_ledger_rederives_finalized_review(self):
        pending = self.prepare()
        mod.finalize_independent_review(self.rd, self.certificate(pending))
        result = lane_gate.review()
        replay = lane_gate.review(lane_gate.load_stage(), result["source_ledger"])
        self.assertEqual(replay["aggregate"], result["aggregate"])

    def test_real_message_landing_normalizes_artifacts_and_keeps_admitted_stage(self):
        self.env["unattended"] = True
        args = SimpleNamespace(job="fixture", unattended=True, skip_scope=False, human_observer="", controller_heartbeat=True)
        prof = mod.load_profile("ops-readonly")
        def render(env, profile, rd):
            rd.mkdir(parents=True)
            (rd / "prompt.md").write_text("read-only health")
            (rd / "manifest.json").write_text("{}")
            return {}
        def preflight(env):
            heartbeat = json.loads((lane_gate.state_dir() / f"heartbeat-{env['id']}.json").read_text())
            self.assertEqual(heartbeat["pid"], os.getpid())
            return {"admit": True, "profile": prof, "lane": {"admit": True}}
        def execute(cmd, rd, *args, **kwargs):
            (rd / "events.jsonl").write_text('{"sessionID":"producer-session"}\n')
            stage = lane_gate.load_stage()
            stage["current_stage"] = "S3"
            lane_gate.save_stage(stage)
            return SimpleNamespace(returncode=0)
        audit = {"tokens": {}, "denials": [], "write_attempts": [], "mutating_commands": [], "verifier_peeks": []}
        with mock.patch.object(mod, "RUNS", self.root / "runs"), \
                mock.patch.object(mod.lane_gate, "load_envelope", return_value=self.env), \
                mock.patch.object(mod, "run_preflight", side_effect=preflight), \
                mock.patch.object(mod, "render_bundle", side_effect=render), \
                mock.patch.object(mod, "run_profile_process", side_effect=execute), \
                mock.patch.object(mod, "arm_env", return_value={}), \
                mock.patch.object(mod, "audit_events", return_value=audit), \
                mock.patch.object(mod, "_git_status", return_value=set()), \
                mock.patch.object(mod, "final_text", return_value='{"read_only":true}'):
            self.assertEqual(mod.cmd_run(args), 0)
        rd = next((self.root / "runs").iterdir())
        self.assertEqual((rd / "artifact.out").read_bytes(), self.dest.read_bytes())
        self.assertTrue((rd / "pending-review.json").exists())
        self.assertEqual(lane_gate.load_ledger()[-1]["verification_status"], "pending_independent")
        self.assertEqual(lane_gate.load_stage()["jobs_completed"], {"S2": 2})

    def test_changed_attempt_rejects_stale_attestation(self):
        pending = self.prepare()
        st = lane_gate.load_stage()
        st["qualification"] = {"at": "a-new-attempt"}
        lane_gate.save_stage(st)
        self.assertIn("error", mod.finalize_independent_review(self.rd, self.certificate(pending)))


class DispatchEvidence(unittest.TestCase):
    def test_card_request_is_included_without_changing_historical_prompts(self):
        env = mk_env(task="Collect the current snapshot for operator triage")
        prof = mod.load_profile("ops-readonly")
        self.assertNotIn(env["task"], mod.build_prompt(env, prof))
        self.assertIn(env["task"], mod.build_prompt(dict(env, dispatch_card=True), prof))

    def test_artifact_must_match_successful_original_tool_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            rd = Path(tmp)
            (rd / "artifact.out").write_text('{"host":"idc02"}')
            state = {"status": "completed", "input": {"command": "python3 scripts/devnest/host_snapshot.py"},
                     "metadata": {"exit": 0}, "output": '{"host":"idc02"}'}
            event = {"part": {"tool": "bash", "state": state}}
            (rd / "events.jsonl").write_text(json.dumps(event) + "\n")
            self.assertTrue(mod.artifact_matches_snapshot(rd))
            (rd / "artifact.out").write_text('{"host":"fabricated"}')
            self.assertFalse(mod.artifact_matches_snapshot(rd))
            (rd / "artifact.out").write_text('{"host":"idc02"}')
            state["metadata"]["exit"] = 1
            (rd / "events.jsonl").write_text(json.dumps(event) + "\n")
            self.assertFalse(mod.artifact_matches_snapshot(rd))


class HumanWatch(unittest.TestCase):
    def test_confirmation_records_measured_minutes_and_observer(self):
        result = mod.confirm_human_watch("tony", "j-test", 90,
                                        read=lambda _: "watched j-test")
        self.assertEqual(result["human_minutes"], 1.5)
        self.assertEqual(result["human_observer"], "tony")
        self.assertTrue(result["human_watch_confirmed"])
        self.assertIn("human_watch_confirmed_at", result)

    def test_decline_eof_or_wrong_job_never_records_watch_minutes(self):
        for read in (lambda _: "no", lambda _: "watched other-job",
                     mock.Mock(side_effect=EOFError)):
            result = mod.confirm_human_watch("tony", "j-test", 90, read=read)
            self.assertEqual(result["human_minutes"], 0)
            self.assertFalse(result["human_watch_confirmed"])

    def test_invalid_duration_never_prompts_or_records_watch(self):
        for seconds in (0, -1, float("nan"), float("inf"), True):
            read = mock.Mock()
            result = mod.confirm_human_watch("tony", "j-test", seconds, read=read)
            self.assertEqual(result["human_minutes"], 0)
            read.assert_not_called()

    def test_observer_requires_supervised_interactive_run(self):
        for unattended, tty in ((True, True), (False, False)):
            args = SimpleNamespace(human_observer="tony", unattended=unattended,
                                   job="does-not-exist", skip_scope=False)
            with mock.patch.object(mod.sys, "stdin") as stdin:
                stdin.isatty.return_value = tty
                self.assertEqual(mod.cmd_run(args), 2)

    def test_no_run_or_metric_without_watcher_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            def render(env, prof, rd):
                rd.mkdir(parents=True)
                (rd / "prompt.md").write_text("read-only canary")
                return {}

            args = SimpleNamespace(human_observer="tony", unattended=False,
                                   job="fixture", skip_scope=False)
            with mock.patch.object(mod.sys, "stdin") as stdin, \
                    mock.patch.object(mod, "RUNS", Path(td)), \
                    mock.patch.object(mod.lane_gate, "load_envelope", return_value=mk_env()), \
                    mock.patch.object(mod, "run_preflight", return_value={"admit": True, "profile": {}}) as preflight, \
                    mock.patch.object(mod, "render_bundle", side_effect=render), \
                    mock.patch("builtins.input", return_value=""), \
                    mock.patch.object(mod, "run_profile_process") as process, \
                    mock.patch.object(mod.lane_gate, "record_metric") as record:
                stdin.isatty.return_value = True
                self.assertEqual(mod.cmd_run(args), 2)
                self.assertFalse(preflight.call_args.args[0]["unattended"])
                process.assert_not_called()
                record.assert_not_called()

    def test_nonobserver_process_keeps_captured_event_behavior(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td)
            result = mod.run_profile_process(
                [sys.executable, "-c", "print('ordinary-event')"], rd, 5,
                dict(os.environ), cwd=td)
            self.assertEqual(result.returncode, 0)
            self.assertIn("ordinary-event", (rd / "events.jsonl").read_text())

    def test_live_process_timeout_preserves_partial_events(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td)
            with self.assertRaises(mod.subprocess.TimeoutExpired):
                mod.run_profile_process(
                    [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(5)"],
                    rd, 0.2, dict(os.environ), observer="tony", cwd=td)
            self.assertIn("started", (rd / "events.jsonl").read_text())

    def test_live_process_writes_events_before_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td)
            result = mod.run_profile_process(
                [sys.executable, "-c", "print('watch-event')"], rd, 5,
                dict(os.environ), observer="tony", cwd=td)
            self.assertEqual(result.returncode, 0)
            self.assertIn("watch-event", (rd / "events.jsonl").read_text())
            self.assertEqual((rd / "stderr.log").read_text(), "")


class LintProfiles(unittest.TestCase):
    def test_all_committed_profiles_lint_clean(self):
        pids = mod.list_profiles()
        self.assertEqual(sorted(pids),
                         ["artifact-write", "branch-code",
                          "branch-code-supervised-pilot", "doc-draft",
                          "gs-capture-eval", "mddb-sequence",
                          "ops-readonly",
                          "ops-remote-read", "ssot-research",
                          "storage-dryrun"])
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

    def test_branch_code_git_allowlist_is_worktree_scoped(self):
        p = mod.load_profile("branch-code")
        bash = p["permission"]["bash"]
        self.assertNotIn("git add *", bash)
        roots = ("scripts", "tests", "evals", "docs/kb",
                 "docs/reports", "docs/ssot/jobs")
        self.assertNotIn("git add docs/*", bash)
        self.assertNotIn("git add -- docs/*", bash)
        self.assertEqual(
            p["allowed_paths"],
            ["scripts/", "tests/", "docs/kb/", "docs/reports/",
             "docs/ssot/jobs/", "evals/"])
        for root in roots:
            self.assertEqual(bash[f"git add {root}/*"], "allow")
            self.assertEqual(bash[f"git add -- {root}/*"], "allow")
        for command in (
            "git add .", "git add -A", "git push *", "git merge *",
            "git rebase *", "git switch *", "git checkout *",
            "git branch *", "git worktree *",
        ):
            self.assertNotIn(command, bash)
        self.assertEqual(bash["git commit *"], "allow")
        self.assertEqual(p["status"], "disabled")

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
        for pid in ("gs-capture-eval", "mddb-sequence", "ops-readonly",
                    "ssot-research", "storage-dryrun"):
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

    def test_branch_code_prompt_allows_local_commit_but_not_publish(self):
        prof = mod.load_profile("branch-code")
        prompt = mod.agent_prompt(mk_env("branch-code"), prof)
        self.assertIn("committing inside this isolated worktree", prompt)
        self.assertIn("staging one declared in-scope path at a time", prompt)
        self.assertIn("Never push, merge, rebase", prompt)
        self.assertNotIn("Do not stage or commit Git changes", prompt)
        self.assertEqual(prof["status"], "disabled")

    def test_readonly_prompt_forbids_git_writes(self):
        prof = mod.load_profile("ops-readonly")
        prompt = mod.agent_prompt(mk_env(), prof)
        self.assertIn("Do not stage or commit Git changes", prompt)

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
        self.assertEqual(len(jobs), 6)
        for j in jobs:
            env = lane_gate.load_envelope(j)
            self.assertEqual(lane_gate.lint_envelope(env), [], j.name)
            self.assertIn("profile", env)

    def test_enabled_job_envelopes_consistent(self):
        for pid in ("gs-capture-eval", "mddb-sequence", "ops-readonly",
                    "ssot-research", "storage-dryrun"):
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
