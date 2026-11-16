"""Contract tests for scripts/colab/packs/kk-mac-image-render-poc
(card adobe-stock-kk-mac-render-poc).

Stdlib only: render.py defers torch/diffusers into render_one, so the
module imports and every gate evaluates without the KK-Mac venv.

Covers:
  - pack.yml passes the nest-pack-submit validator
  - the checked-in request template is disabled and can never render
  - evaluate() fails closed on every listed fail-closed condition, and
    passes end-to-end on synthetic facts for an approved request
  - main() writes preflight.json + verdict.json(fail) and exits nonzero
    for the disabled template — artifact evidence without a render
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PACK_DIR = REPO / "scripts/colab/packs/kk-mac-image-render-poc"
RENDER_PY = PACK_DIR / "render.py"
TEMPLATE = PACK_DIR / "inputs/render-request.json"
NEST_SUBMIT = REPO / "scripts/ada/nest-pack-submit.py"

MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
REVISION = "462165984030d82259a11f4367a4eed129e94a7b"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RENDER = load_module("kk_image_render_poc", RENDER_PY)
SUBMIT = load_module("nest_pack_submit", NEST_SUBMIT)


def template_request():
    return json.loads(TEMPLATE.read_text())


def approved_request():
    req = template_request()
    req.update(
        status="approved",
        request_id="test-render-001",
        owner_approved=True,
        approved_by="tony",
        approved_at="2026-11-14T00:00:00Z",
        render_window={"not_before_utc": "2026-01-01T00:00:00Z",
                       "not_after_utc": "2030-01-01T00:00:00Z"})
    return req


def make_facts(root, **over):
    root = Path(root)
    venv = root / "venv"
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    (venv / "bin" / "python").write_text("")
    snap = root / "snap" / REVISION
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "model_index.json").write_text("{}")
    facts = {
        "now": time.time(),
        "hostname": "test-host",
        "platform": "test",
        "venv_dir": str(venv),
        "venv_python": str(venv / "bin" / "python"),
        "sys_prefix": str(venv),
        "sys_executable": str(venv / "bin" / "python"),
        "disk_free_gb": 100.0,
        "load_1m": 0.5,
        "manifest": {"model_id": MODEL_ID, "revision": REVISION,
                     "snapshot_dir": str(snap)},
        "manifest_error": None,
        "snapshot_dir": str(snap),
        "snapshot_missing": [],
    }
    facts.update(over)
    return facts


def failed_ids(checks):
    return {c["id"] for c in checks if c["status"] != "pass"}


class PackContractTest(unittest.TestCase):
    def test_pack_yml_passes_submit_validation(self):
        spec = yaml.safe_load((PACK_DIR / "pack.yml").read_text())
        self.assertEqual(SUBMIT.validate(spec, PACK_DIR.name), [])
        self.assertEqual(spec["name"], "kk-mac-image-render-poc")
        self.assertEqual(spec["needs"]["gpu_gb"], 0)
        self.assertGreaterEqual(spec["needs"]["disk_gb"], 30)
        self.assertTrue(spec.get("run_sh"))
        self.assertNotIn("run", spec)
        for glob in spec["artifacts"]:
            self.assertTrue(
                glob.startswith("packs/kk-mac-image-render-poc/out/"),
                glob)

    def test_render_py_is_stdlib_at_top_level(self):
        """torch/diffusers must stay out of module scope so the file
        imports anywhere (worker gate evaluation, these tests)."""
        stdlib = getattr(sys, "stdlib_module_names", frozenset(
            {"argparse", "hashlib", "json", "os", "platform", "re",
             "socket", "struct", "sys", "time", "traceback", "datetime"}))
        tree = ast.parse(RENDER_PY.read_text())
        imported = set()
        for node in tree.body:  # module level only
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])
        imported.discard("__future__")
        self.assertEqual(imported - stdlib, set())


class DisabledTemplateTest(unittest.TestCase):
    def test_checked_in_request_is_disabled(self):
        req = template_request()
        self.assertNotEqual(req["status"], "approved")
        self.assertIs(req["owner_approved"], False)
        self.assertIsNone(req["approved_by"])
        self.assertIs(req["adobe_upload"], False)
        self.assertEqual(req["render"]["count"], 1)
        self.assertEqual(req["model"]["id"], MODEL_ID)
        self.assertEqual(req["model"]["revision"], REVISION)
        self.assertGreaterEqual(req["limits"]["min_disk_free_gb"], 30.0)
        self.assertGreater(req["limits"]["max_load_1m"], 0)
        self.assertRegex(req["output_name"], r"^[A-Za-z0-9._-]+\.png$")

    def test_template_fails_closed_at_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = RENDER.evaluate(template_request(), make_facts(tmp))
        self.assertIn("request_approved", failed_ids(checks))
        self.assertIn("owner_approved", failed_ids(checks))
        self.assertIn("approval_recorded", failed_ids(checks))
        self.assertIn("render_window", failed_ids(checks))  # lapsed window
        # non-approval gates still pass — the file is well-formed,
        # it is simply not allowed to render
        self.assertNotIn("request_parses", failed_ids(checks))
        self.assertNotIn("adobe_upload_disabled", failed_ids(checks))
        self.assertNotIn("model_pin_match", failed_ids(checks))

    def test_main_writes_evidence_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            (pack / "inputs").mkdir()
            (pack / "inputs" / "render-request.json").write_text(
                TEMPLATE.read_text())
            rc = RENDER.main(["--pack-dir", str(pack)])
            self.assertEqual(rc, 2)
            pre = json.loads((pack / "out" / "preflight.json").read_text())
            self.assertEqual(pre["verdict"], "fail")
            self.assertIn("request_approved",
                          {c["id"] for c in pre["checks"]
                           if c["status"] == "fail"})
            verdict = json.loads(
                (pack / "out" / "verdict.json").read_text())
            self.assertEqual(verdict["verdict"], "fail")
            self.assertIs(verdict["rendered"], False)
            self.assertIs(verdict["adobe_upload"], False)
            self.assertFalse((pack / "out" / "render.png").exists())
            self.assertFalse(
                (pack / "out" / "render-manifest.json").exists())


class GateMatrixTest(unittest.TestCase):
    def test_approved_request_passes_all_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = RENDER.evaluate(approved_request(), make_facts(tmp))
        self.assertEqual(failed_ids(checks), set(),
                         msg=json.dumps(checks, indent=1))

    def test_every_fail_closed_condition(self):
        cases = []

        def mutate(req=None, **fact_over):
            req = req if req is not None else approved_request()
            return req, fact_over

        r = approved_request(); r["status"] = "queued"
        cases.append((mutate(r), {"request_approved"}))
        r = approved_request(); r["owner_approved"] = False
        cases.append((mutate(r), {"owner_approved"}))
        r = approved_request(); r["approved_by"] = ""
        cases.append((mutate(r), {"approval_recorded"}))
        r = approved_request(); r["adobe_upload"] = True
        cases.append((mutate(r), {"adobe_upload_disabled"}))
        r = approved_request(); del r["adobe_upload"]
        cases.append((mutate(r), {"adobe_upload_disabled"}))
        r = approved_request(); r["render"]["count"] = 4
        cases.append((mutate(r), {"single_render"}))
        r = approved_request(); r["render"]["width"] = 100000
        cases.append((mutate(r), {"render_bounds"}))
        r = approved_request(); r["render"]["num_inference_steps"] = 999
        cases.append((mutate(r), {"render_bounds"}))
        r = approved_request(); r["output_name"] = "../escape.png"
        cases.append((mutate(r), {"output_name_safe"}))
        r = approved_request(); r["prompt"] = ""
        cases.append((mutate(r), {"prompt_present"}))
        r = approved_request()
        r["render_window"] = {"not_before_utc": "2026-01-01T00:00:00Z",
                              "not_after_utc": "2026-01-02T00:00:00Z"}
        cases.append((mutate(r), {"render_window"}))
        r = approved_request(); r["model"]["revision"] = "0" * 40
        cases.append((mutate(r), {"model_pin_match"}))
        r = approved_request(); del r["model"]
        cases.append((mutate(r), {"model_pin_match"}))
        r = approved_request(); del r["limits"]
        cases.append((mutate(r), {"disk_floor", "load_limit"}))

        fact_cases = [
            ({"manifest": None, "manifest_error": "FileNotFoundError",
              "snapshot_dir": None},
             {"manifest_pinned", "model_pin_match", "snapshot_present"}),
            ({"snapshot_missing": ["unet/model.safetensors"]},
             {"snapshot_present"}),
            ({"disk_free_gb": 5.0}, {"disk_floor"}),
            ({"disk_free_gb": None}, {"disk_floor"}),
            ({"load_1m": 99.0}, {"load_limit"}),
            ({"load_1m": None}, {"load_limit"}),
            ({"sys_prefix": "/usr"}, {"venv_isolated"}),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            for i, ((req, fo), want) in enumerate(cases):
                with self.subTest(case=i):
                    checks = RENDER.evaluate(req, make_facts(tmp, **fo))
                    self.assertTrue(want <= failed_ids(checks),
                                    f"want {want} in {failed_ids(checks)}")
            for i, (fo, want) in enumerate(fact_cases):
                with self.subTest(fact_case=i):
                    checks = RENDER.evaluate(
                        approved_request(), make_facts(tmp, **fo))
                    self.assertTrue(want <= failed_ids(checks),
                                    f"want {want} in {failed_ids(checks)}")

    def test_bad_request_json_fails_first_gate(self):
        checks = RENDER.evaluate("JSONDecodeError: Expecting value", {})
        self.assertEqual([c["id"] for c in checks], ["request_parses"])
        self.assertEqual(checks[0]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
