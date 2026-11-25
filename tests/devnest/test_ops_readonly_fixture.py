"""Regression tests for the ops-readonly fixture spec
(card fixture-spec-bug-ops-readonly-artifact-e-95ef6e): the fixture
must expose ONE machine-readable required-key list that matches both
the held-out verifier's `req` tuple and the prompt's field list, so a
card's action.expect.required_keys can never again carry the
branch-code [artifact, tests, verifier] shape against a health-JSON
artifact.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FIXTURE = (REPO / "evals/opencode-lane/profiles/ops-readonly"
           / "fixture")
TASK_YAML = FIXTURE / "task.yaml"
VERIFY_PY = FIXTURE / "verify.py"
PROMPT_MD = FIXTURE / "prompt.md"
HOST_SNAPSHOT = REPO / "scripts/devnest/host_snapshot.py"


def _load_verify():
    spec = importlib.util.spec_from_file_location(
        "ops_readonly_verify", VERIFY_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_host_snapshot():
    spec = importlib.util.spec_from_file_location(
        "host_snapshot", HOST_SNAPSHOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _verifier_required_keys():
    """Pull the `req = (...)` tuple out of verify.py's verify() — the
    held-out contract the fixture spec must mirror."""
    tree = ast.parse(VERIFY_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "req":
                    return [e.value for e in node.value.elts
                            if isinstance(e, ast.Constant)]
    raise AssertionError("verify.py has no `req` tuple")


class FixtureSpecConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = yaml.safe_load(TASK_YAML.read_text())
        cls.contract = cls.task["contract"]
        cls.required_keys = cls.contract["required_keys"]
        cls.field_keys = list(cls.contract["required_fields"])
        cls.verify_keys = _verifier_required_keys()
        cls.prompt = PROMPT_MD.read_text()

    def test_required_keys_matches_required_fields(self):
        self.assertEqual(sorted(self.required_keys),
                         sorted(self.field_keys))

    def test_required_keys_matches_verifier_req(self):
        self.assertEqual(sorted(self.required_keys),
                         sorted(self.verify_keys))

    def test_prompt_lists_every_required_key(self):
        for k in self.required_keys:
            self.assertIn(k, self.prompt, k)

    def test_no_branch_code_expect_shape(self):
        # the 2026-11-07 bug: expect.required_keys=[artifact, tests,
        # verifier] on an ops-readonly card. The fixture contract must
        # never advertise that shape.
        self.assertNotIn("artifact", self.required_keys)
        self.assertNotIn("tests", self.required_keys)
        self.assertNotIn("verifier", self.required_keys)


class OpsReadonlyVerifyTest(unittest.TestCase):
    """verify() end-to-end on a synthetic run dir — a real
    host_snapshot.collect() artifact must pass, and dropping any
    required key must fail the 'required fields' check."""

    def setUp(self):
        self.v = _load_verify()
        self.hs = _load_host_snapshot()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rd = Path(self.tmp.name)

    def _run_dir(self, artifact):
        snap = self.hs.collect()
        (self.rd / "manifest.json").write_text(json.dumps(
            {"envelope": {"target_host": snap["host"],
                          "artifact": {"path": "out/health.json"}}}))
        (self.rd / "artifact.out").write_text(json.dumps(artifact))
        return self.v.verify(self.rd)

    def test_good_artifact_passes(self):
        res = self._run_dir(self.hs.collect())
        self.assertEqual(res["verdict"], "pass", res)

    def test_missing_required_key_fails_required_fields(self):
        art = self.hs.collect()
        art.pop("disk_root_pct")
        res = self._run_dir(art)
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["required fields"])

    def test_wrong_host_fails(self):
        art = self.hs.collect()
        art["host"] = "not-this-host"
        res = self._run_dir(art)
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["artifact host is this host"])


if __name__ == "__main__":
    unittest.main()
