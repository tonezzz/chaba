import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts/colab/devnest-model-slot-runner.py"
SPEC = importlib.util.spec_from_file_location("devnest_model_slot", RUNNER_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
HF_SPEC = importlib.util.spec_from_file_location(
    "devnest_hf_model_slot",
    ROOT / "scripts/colab/packs/devnest-model-slot-30m/run_hf_slot.py")
HF_RUNNER = importlib.util.module_from_spec(HF_SPEC)
HF_SPEC.loader.exec_module(HF_RUNNER)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class ModelSlotRunnerTests(unittest.TestCase):
    def test_parses_plain_and_wrapped_json(self):
        self.assertEqual(RUNNER.parse_json_response('{"route":"read_only"}'),
                         {"route": "read_only"})
        self.assertEqual(
            RUNNER.parse_json_response('result: {"route":"read_only"} done'),
            {"route": "read_only"})
        self.assertEqual(
            HF_RUNNER.parse_json_response('result: {"route":"read_only"} done'),
            {"route": "read_only"})

    def test_verifier_requires_exact_keys_and_types(self):
        expected = {"mutation": False, "failed_units": 2}
        self.assertEqual(RUNNER.verify_response(expected, expected),
                         (True, "exact_match"))
        self.assertEqual(
            RUNNER.verify_response(
                {"mutation": 0, "failed_units": 2}, expected)[0],
            False)
        self.assertEqual(
            RUNNER.verify_response(
                {"mutation": False, "failed_units": 2, "extra": 1},
                expected),
            (False, "keys_mismatch"))
        self.assertEqual(
            HF_RUNNER.verify_response(expected, expected),
            (True, "exact_match"))

    def test_hf_snapshot_integrity_check_uses_manifest_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            model_dir = Path(temp)
            content = b"synthetic model config"
            (model_dir / "config.json").write_bytes(content)
            manifest = {
                "files": {
                    "config.json": {
                        "bytes": len(content),
                        "sha256": HF_RUNNER.sha256_file(
                            model_dir / "config.json"),
                    }
                }
            }
            HF_RUNNER.verify_model_snapshot(model_dir, manifest)
            manifest["files"]["config.json"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                HF_RUNNER.verify_model_snapshot(model_dir, manifest)

    def test_five_synthetic_fixtures_are_declared(self):
        fixtures = json.loads(RUNNER.FIXTURES.read_text(encoding="utf-8"))
        self.assertEqual(len(fixtures), 5)
        self.assertEqual(len({fixture["id"] for fixture in fixtures}), 5)
        self.assertTrue(all(fixture["expected"] for fixture in fixtures))

    def test_pack_variants_are_bounded_and_target_the_right_workers(self):
        colab = yaml.safe_load(
            (ROOT / "scripts/colab/packs/devnest-model-slot-30m/pack.yml")
            .read_text())
        mac = yaml.safe_load(
            (ROOT / "scripts/colab/packs/kk-mac-devnest-model-slot-30m/pack.yml")
            .read_text())
        self.assertEqual(colab["timeout_s"], 1800)
        self.assertEqual(colab["needs"]["gpu_gb"], 10)
        self.assertEqual(colab["requires"], ["devnest-qwen3-8b-hf-prestage"])
        self.assertEqual(mac["timeout_s"], 1800)
        self.assertEqual(mac["needs"]["ram_gb"], 30)
        self.assertNotIn("gpu_gb", mac["needs"])
        self.assertNotIn("ollama pull", mac["prep"])
        self.assertEqual(
            mac["fetch"],
            ["queue/devnest-model-slot-runner.py",
             "queue/devnest-model-slot-fixtures.json"])
        prestage = yaml.safe_load(
            (ROOT / "scripts/colab/packs/devnest-qwen3-8b-hf-prestage/pack.yml")
            .read_text())
        self.assertEqual(prestage["needs"]["ram_gb"], 20)
        self.assertEqual(prestage["needs"]["disk_gb"], 40)
        self.assertEqual(prestage["timeout_s"], 5400)

    def test_qwen_prefetch_follows_warmup_for_overlap(self):
        sys.path.insert(0, str(ROOT / "scripts/colab"))
        try:
            spec = importlib.util.spec_from_file_location(
                "devnest_slot_jobs", ROOT / "scripts/colab/JOBS.py")
            jobs = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(jobs)
        finally:
            sys.path.pop(0)
        names = [job["name"] for job in jobs.JOBS]
        self.assertEqual(names[0], "t4-session-warmup")
        self.assertEqual(names[1], "restore-devnest-qwen3-hf-for-slot")
        syntax = subprocess.run(
            ["bash", "-n"], input=jobs._DEVNEST_HF_SLOT_PREP,
            text=True, capture_output=True, check=False)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_run_fixture_records_tokens_and_verdict(self):
        fixture = {
            "id": "route-read-only",
            "prompt": "Classify the synthetic read-only request.",
            "expected": {"route": "read_only", "mutation": False},
        }
        fake = FakeResponse({
            "response": '{"route":"read_only","mutation":false}',
            "eval_count": 12,
            "eval_duration": 2_000_000_000,
            "prompt_eval_count": 30,
            "load_duration": 500_000_000,
        })
        with patch.object(RUNNER.urllib.request, "urlopen",
                          return_value=fake):
            row = RUNNER.run_fixture(
                "http://127.0.0.1:11434", "qwen3:8b", fixture)
        self.assertTrue(row["pass"])
        self.assertEqual(row["completion_tokens"], 12)
        self.assertEqual(row["tokens_per_second"], 6.0)
        self.assertEqual(row["load_s"], 0.5)

    def test_cache_save_timeout_is_best_effort(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_root = root / "models"
            model_root.mkdir()
            target = root / "qwen3.tar.zst"
            with patch.object(RUNNER.shutil, "which", return_value="/usr/bin/zstd"), \
                    patch.object(
                        RUNNER.subprocess, "run",
                        side_effect=subprocess.TimeoutExpired("tar", 600)):
                self.assertFalse(RUNNER.maybe_save_ollama_cache(
                    str(target), str(model_root)))
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix(
                target.suffix + ".incomplete").exists())


if __name__ == "__main__":
    unittest.main()
