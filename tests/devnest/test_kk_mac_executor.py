import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.devnest.kk_mac_executor import (
    admission_gate, artifact_allowed, extract_json, probe, run_contract,
    verify)


def _task(**kw):
    t = {"id": "t1", "card": "c1", "task_class": "summary",
         "prompt": "summarize the host evidence", "expect": {},
         "artifact": "evals/kk-mac-lane/out/c1.json"}
    t.update(kw)
    return t


def _ok_run(response="done", **kw):
    def run(task_class, prompt, **kwargs):
        return {"ok": True, "response": response,
                "usage": {"eval_count": 7}, "admission": {},
                "model": kwargs.get("model")}
    return run


class _NullMonitor:
    samples = []

    def start(self):
        pass

    def stop(self):
        pass

    def worst_reasons(self):
        return []


class VerifyTests(unittest.TestCase):
    def test_summary_needs_nonempty_bounded_text(self):
        v = verify("summary", "a tight summary", {})
        self.assertEqual(v["verdict"], "pass")
        self.assertFalse(verify("summary", "  ", {})["checks"]
                         ["response_nonempty"])
        self.assertFalse(verify("summary", "x" * 20001, {})["checks"]
                         ["response_bounded"])

    def test_json_classes_must_parse(self):
        v = verify("safe_route", "not json at all", {})
        self.assertEqual(v["verdict"], "fail")
        self.assertFalse(v["checks"]["json_parses"])
        v = verify("safe_route", '{"route": "free_lane"}', {})
        self.assertEqual(v["verdict"], "pass")

    def test_fenced_json_is_accepted(self):
        v = verify("structured_extract",
                   '```json\n{"host": "x", "n": 3}\n```',
                   {"required_keys": ["host", "n"]})
        self.assertEqual(v["verdict"], "pass")

    def test_required_keys_enums_facts(self):
        expect = {"required_keys": ["route", "why"],
                  "enums": {"route": ["free_lane", "devin"]},
                  "facts": ["11434"]}
        ok = verify("safe_route",
                    '{"route": "free_lane", "why": "port 11434"}',
                    expect)
        self.assertEqual(ok["verdict"], "pass")
        bad_route = verify("safe_route",
                           '{"route": "moon", "why": "port 11434"}',
                           expect)
        self.assertEqual(bad_route["verdict"], "fail")
        self.assertFalse(bad_route["checks"]["enum:route"])
        missing_fact = verify(
            "structured_extract", '{"a": 1}', {"facts": ["absent-word"]})
        self.assertFalse(missing_fact["checks"]["fact:absent-word"])

    def test_extract_json_tolerates_prose(self):
        self.assertEqual(
            extract_json('here is the answer: {"a": 1} thanks'),
            {"a": 1})
        self.assertIsNone(extract_json("no object"))


class AdmissionGateTests(unittest.TestCase):
    def test_denied_class_is_a_task_reason(self):
        g = admission_gate("code_mutation", "do it", snap={"reasons": []})
        self.assertFalse(g["eligible"])
        self.assertIn("task:class_not_admitted:code_mutation",
                      g["reasons"])

    def test_prompt_bounds(self):
        g = admission_gate("summary", "", snap={"reasons": []})
        self.assertIn("task:prompt_empty", g["reasons"])
        g = admission_gate("summary", "x" * 6001, snap={"reasons": []})
        self.assertIn("task:prompt_too_long", g["reasons"])

    def test_heartbeat_reasons_merge(self):
        g = admission_gate("summary", "ok",
                           snap={"reasons": ["heartbeat_stale"]})
        self.assertFalse(g["eligible"])
        self.assertIn("heartbeat_stale", g["reasons"])

    def test_probe_fails_closed_on_error(self):
        with patch("scripts.devnest.kk_mac_executor"
                   ".kk_mac_admission.snapshot",
                   side_effect=OSError("mddb down")):
            p = probe()
        self.assertFalse(p["eligible"])
        self.assertIn("probe_failed:OSError", p["reasons"][0])


class ArtifactRootsTests(unittest.TestCase):
    def test_allowed_roots(self):
        self.assertTrue(artifact_allowed("evals/kk-mac-lane/out/x.json"))
        self.assertTrue(artifact_allowed("reports/x.json"))
        self.assertFalse(artifact_allowed("scripts/x.py"))
        self.assertFalse(artifact_allowed("../evil"))
        self.assertFalse(artifact_allowed("/abs/path"))
        self.assertFalse(artifact_allowed(""))


class RunContractTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.wt = Path(self.td.name) / "wt"
        self.wt.mkdir()
        self.taskdir = Path(self.td.name) / "task"
        self.snap = {"eligible": True, "reasons": []}
        self.mem = {"ok": True, "free_pct": 80.0, "level": None,
                    "raw": "", "at": "t", "error": None}

    def run_c(self, task=None, **kw):
        kw.setdefault("mem_sample", lambda host: dict(self.mem))
        kw.setdefault("make_monitor", lambda host: _NullMonitor())
        return run_contract(task or _task(), snap=self.snap,
                            worktree=self.wt, taskdir=self.taskdir, **kw)

    def test_pass_persists_artifact_and_verdict(self):
        r = self.run_c(run_task=_ok_run("the summary"))
        self.assertEqual(r["verdict"], "pass")
        self.assertTrue(r["artifact_written"])
        art = self.wt / "evals/kk-mac-lane/out/c1.json"
        self.assertTrue(art.is_file())
        saved = json.loads(art.read_text())
        self.assertEqual(saved["response"], "the summary")
        self.assertEqual(saved["usage"]["eval_count"], 7)
        self.assertTrue((self.taskdir / "verdict.json").is_file())
        self.assertTrue((self.taskdir / "kk_mac_result.json").is_file())

    def test_ineligible_lane_falls_back(self):
        self.snap = {"eligible": False,
                     "reasons": ["heartbeat_stale"]}
        r = self.run_c(run_task=_ok_run())
        self.assertEqual(r["verdict"], "fallback")
        self.assertIn("heartbeat_stale", r["reasons"])

    def test_executor_error_falls_back(self):
        def boom(*a, **k):
            raise RuntimeError("ssh denied")
        r = self.run_c(run_task=boom)
        self.assertEqual(r["verdict"], "fallback")
        self.assertIn("executor_error:RuntimeError", r["reasons"][0])

    def test_run_declined_falls_back(self):
        r = self.run_c(run_task=lambda *a, **k: {
            "ok": False, "admission": {"reasons": ["ollama_unhealthy"]}})
        self.assertEqual(r["verdict"], "fallback")
        self.assertIn("ollama_unhealthy", r["reasons"][0])

    def test_invalid_output_falls_back(self):
        r = self.run_c(task=_task(
            task_class="safe_route",
            expect={"required_keys": ["route"]}),
            run_task=_ok_run("not json"))
        self.assertEqual(r["verdict"], "fallback")
        self.assertIn("invalid_output", r["reasons"][0])

    def test_contract_violations_fail_closed(self):
        r = self.run_c(task=_task(task_class="code_mutation"))
        self.assertEqual(r["verdict"], "fail")
        self.assertIn("class_not_admitted", r["reasons"][0])
        r = self.run_c(task=_task(artifact="scripts/x.py"))
        self.assertEqual(r["verdict"], "fail")
        self.assertIn("artifact_outside_roots", r["reasons"][0])
        r = self.run_c(task=_task(prompt="  "))
        self.assertEqual(r["verdict"], "fail")

    def test_oversize_prompt_falls_back_not_fails(self):
        r = self.run_c(task=_task(prompt="x" * 6001))
        self.assertEqual(r["verdict"], "fallback")
        self.assertIn("prompt_too_long", r["reasons"])

    def test_memory_preload_floor_blocks_before_run(self):
        self.mem["free_pct"] = 55.0
        called = []
        r = self.run_c(run_task=lambda *a, **k: called.append(1) or
                       _ok_run()( *a, **k))
        self.assertEqual(r["verdict"], "fallback")
        self.assertTrue(any(x.startswith("memory_preload_floor")
                            for x in r["reasons"]))
        self.assertEqual(called, [])
        self.assertEqual(r["memory"]["pre"]["free_pct"], 55.0)

    def test_memory_sample_failure_fails_closed(self):
        self.mem["ok"] = False
        self.mem["free_pct"] = None
        r = self.run_c(run_task=_ok_run())
        self.assertEqual(r["verdict"], "fallback")
        self.assertIn("memory_sample_failed", r["reasons"])

    def test_memory_during_breach_fails_closed(self):
        class BreachMonitor(_NullMonitor):
            samples = [{"ok": True, "free_pct": 45.0}]

            def worst_reasons(self):
                return ["memory_pressure_abort:45.0%<50.0%"]

        r = self.run_c(run_task=_ok_run("fine"),
                       make_monitor=lambda host: BreachMonitor())
        self.assertEqual(r["verdict"], "fallback")
        self.assertTrue(any(x.startswith("memory_pressure_abort")
                            for x in r["reasons"]))
        self.assertEqual(len(r["memory"]["during"]), 1)

    def test_memory_snapshots_persisted_on_pass(self):
        r = self.run_c(run_task=_ok_run("ok"))
        self.assertEqual(r["verdict"], "pass")
        self.assertEqual(r["memory"]["pre"]["free_pct"], 80.0)
        self.assertIsNotNone(r["memory"]["post"])
        saved = json.loads(
            (self.wt / "evals/kk-mac-lane/out/c1.json").read_text())
        self.assertIn("memory", saved)

    def test_facts_verified_independently(self):
        r = self.run_c(task=_task(
            task_class="operator_brief",
            expect={"required_keys": ["brief"],
                    "facts": ["six hosts", "zero errors"]}),
            run_task=_ok_run(
                '{"brief": "six hosts, zero errors"}'))
        self.assertEqual(r["verdict"], "pass")
        r = self.run_c(task=_task(
            task_class="operator_brief",
            expect={"facts": ["never said"]}),
            run_task=_ok_run('{"brief": "something else"}'))
        self.assertEqual(r["verdict"], "fallback")


if __name__ == "__main__":
    unittest.main()
