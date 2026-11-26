"""Tests for the offline proposal-to-review compiler."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
SCRIPT = REPO / "evals/opencode-lane/compile_proposal.py"
spec = importlib.util.spec_from_file_location("proposal_compiler", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["proposal_compiler"] = mod
spec.loader.exec_module(mod)


def proposal(case_id="readonly-report"):
    return {
        "case_id": case_id,
        "goal": "Review a synthetic task",
        "recommendation": "Use synthetic data only",
        "viewpoints": {
            "user_value": "Improve visibility with a report",
            "technical": "Validate the synthetic output",
            "operations_safety": "Avoid all live host access",
            "cost_effort": "Keep local compute low",
        },
        "options": [
            {"label": "A", "benefit": "Faster review",
             "tradeoff": "Less detail"},
            {"label": "B", "benefit": "More complete",
             "tradeoff": "More review time"},
        ],
        "assumptions": [],
        "open_questions": [],
        "matching_existing_work": {"status": "not_evaluated", "matches": []},
    }


def snapshot(case_id="readonly-report", **updates):
    value = {
        "source": "synthetic_card_snapshot",
        "card_id": f"SYN-{case_id}",
        "version": 1,
        "case_id": case_id,
        "task_class": "report",
        "risk_level": "low",
        "target_host": "tony-macbook",
        "allowed_paths": ["reports/health-snapshot.json"],
        "mcp_allowlist": [],
        "artifact": {"path": "reports/health-snapshot.json",
                     "schema": "health-report-v1"},
        "verifier": {"type": "held_out_py",
                     "ref": "evals/shadow/fixtures/host-health/verify.py"},
        "done_condition": "The held-out health-report verifier passes.",
        "human_gate_required": False,
        "expected_jev_route": "free_lane",
    }
    value.update(updates)
    return value


class CompileProposal(unittest.TestCase):
    def test_review_package_uses_snapshot_and_jev_not_model_policy(self):
        p = proposal()
        s = snapshot()
        result = mod.compile_proposal(
            p, s, {"lane": "free_lane", "source": "jev_keyword"})
        self.assertTrue(result["ok"], result.get("errors"))
        compiled = result["compiled"]
        self.assertEqual(compiled["proposal"], p)
        self.assertEqual(compiled["card_snapshot"],
                         {"source": s["source"], "id": s["card_id"],
                          "version": s["version"]})
        self.assertEqual(compiled["jev"]["route"], "free_lane")
        self.assertEqual(compiled["policy"]["allowed_paths"],
                         ["reports/health-snapshot.json"])
        self.assertFalse(compiled["policy"]["execution_allowed"])
        self.assertEqual(compiled["status"], "proposal_ready")

    def test_missing_target_requires_clarification(self):
        p = proposal("docs-only")
        p["open_questions"] = ["Which repository should receive the checklist?"]
        s = snapshot(
            "docs-only", task_class="artifact_write", target_host=None,
            allowed_paths=["docs/reports/plan-route-checklist.md"],
            artifact={"path": "docs/reports/plan-route-checklist.md",
                      "schema": "markdown-checklist-v1"},
            human_gate_required=True,
            expected_jev_route="free_lane",
        )
        result = mod.compile_proposal(
            p, s, {"lane": "free_lane", "source": "jev_keyword"})
        self.assertTrue(result["ok"], result.get("errors"))
        self.assertEqual(result["compiled"]["status"], "needs_clarification")
        self.assertIsNone(result["compiled"]["policy"]["target_host"])
        self.assertTrue(result["compiled"]["human_review_required"])

    def test_manual_route_requires_human_gate_and_no_write_paths(self):
        p = proposal("physical-hardware")
        s = snapshot(
            "physical-hardware", task_class="manual", risk_level="high",
            target_host="tony-omen", allowed_paths=[], artifact=None,
            verifier={"type": "human",
                      "description": "Tony approves purchase and installation."},
            done_condition="Human approves the hardware decision.",
            human_gate_required=True, expected_jev_route="manual",
        )
        result = mod.compile_proposal(
            p, s, {"lane": "manual", "source": "jev_keyword"})
        self.assertTrue(result["ok"], result.get("errors"))
        self.assertEqual(result["compiled"]["status"], "human_review_required")
        self.assertTrue(result["compiled"]["policy"]["human_gate_required"])
        self.assertFalse(result["compiled"]["policy"]["execution_allowed"])
        self.assertEqual(result["compiled"]["policy"]["allowed_paths"], [])

    def test_model_policy_fields_are_rejected(self):
        p = proposal()
        p["allowed_paths"] = ["/"]
        result = mod.compile_proposal(
            p, snapshot(), {"lane": "free_lane", "source": "jev_keyword"})
        self.assertFalse(result["ok"])
        self.assertIn("model_policy_field_present:allowed_paths",
                      result["errors"])

    def test_snapshot_path_cannot_be_absolute_or_traversal(self):
        for path in ("/", "../reports/health.json"):
            result = mod.compile_proposal(
                proposal(), snapshot(allowed_paths=[path]),
                {"lane": "free_lane", "source": "jev_keyword"})
            self.assertFalse(result["ok"], path)
            self.assertTrue(any(e.startswith("unsafe_snapshot_path:")
                                for e in result["errors"]), path)

    def test_jev_route_mismatch_is_rejected(self):
        result = mod.compile_proposal(
            proposal(), snapshot(),
            {"lane": "manual", "source": "jev_keyword"})
        self.assertFalse(result["ok"])
        self.assertIn("jev_route_mismatch:expected=free_lane:actual=manual",
                      result["errors"])

    def test_snapshot_requires_card_version(self):
        s = snapshot()
        del s["version"]
        result = mod.compile_proposal(
            proposal(), s, {"lane": "free_lane", "source": "jev_keyword"})
        self.assertFalse(result["ok"])
        self.assertIn("missing_snapshot_field:version", result["errors"])

    def test_saved_proposals_compile_from_synthetic_snapshots_and_jev(self):
        from scripts.board import dispatch_repos

        cases = (
            "plan-proposal-v2-readonly.yml",
            "plan-proposal-v2-docs.yml",
            "plan-proposal-v2-hardware.yml",
        )
        with patch.object(dispatch_repos.urllib.request, "urlopen",
                          side_effect=AssertionError("network fallback")):
            for name in cases:
                job = yaml.safe_load(
                    (REPO / "evals/opencode-lane/jobs" / name).read_text())
                proposal_path = REPO / job["artifact"]["path"]
                proposal_doc = json.loads(proposal_path.read_text())
                lane = dispatch_repos.classify_lane(job["jev_input"])
                result = mod.compile_proposal(
                    proposal_doc, job["policy_snapshot"],
                    {"lane": lane, "source": "jev_keyword"},
                )
                self.assertTrue(result["ok"], (name, result.get("errors")))
                compiled = result["compiled"]
                self.assertEqual(lane, job["expected_jev_route"])
                self.assertEqual(compiled["policy"]["allowed_paths"],
                                 job["policy_snapshot"]["allowed_paths"])
                self.assertFalse(compiled["policy"]["execution_allowed"])
                self.assertFalse(compiled["execution_authorized"])
                self.assertEqual(
                    compiled["card_snapshot"]["source"],
                    "synthetic_card_snapshot")

    def test_compiled_hardware_plan_cannot_be_auto_executed(self):
        p = proposal("physical-hardware")
        s = snapshot(
            "physical-hardware", task_class="manual", risk_level="high",
            target_host="tony-omen", allowed_paths=[], artifact=None,
            verifier={"type": "human", "description": "Tony approves."},
            done_condition="Tony approves before any purchase.",
            human_gate_required=True, expected_jev_route="manual",
        )
        result = mod.compile_proposal(
            p, s, {"lane": "manual", "source": "jev_keyword"})
        self.assertTrue(result["ok"], result.get("errors"))
        compiled = result["compiled"]
        self.assertEqual(compiled["status"], "human_review_required")
        self.assertTrue(compiled["human_review_required"])
        self.assertFalse(compiled["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
