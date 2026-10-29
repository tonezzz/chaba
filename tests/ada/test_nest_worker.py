import importlib.util
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

WORKER_PATH = Path(__file__).parents[2] / "scripts/ada/nest-worker.py"
SPEC = importlib.util.spec_from_file_location("nest_worker", WORKER_PATH)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class PartialArtifactUploadTests(unittest.TestCase):
    def test_uploads_only_declared_files_inside_pack(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "out").mkdir()
            declared = root / "out/task-result.json"
            declared.write_text('{"result":"failed"}')
            (root / "out/private.log").write_text("not declared")
            calls = []

            def fake_rc(*args, **kwargs):
                calls.append(args)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            spec = {
                "artifacts": [
                    "packs/cline-bridge/out/task-result.json",
                    "packs/cline-bridge/out/task.patch",
                ],
            }
            with patch.object(worker, "rc", side_effect=fake_rc):
                copied, failed = worker.upload_partial_artifacts(
                    "cline-bridge", spec, td, "gdrive:pilot")

            self.assertEqual(
                copied,
                ["gdrive:pilot/packs/cline-bridge/out/task-result.json"],
            )
            self.assertEqual(failed, [])
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "copyto")
            self.assertEqual(calls[0][1], str(declared))

    def test_rejects_artifact_patterns_with_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []

            def fake_rc(*args, **kwargs):
                calls.append(args)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(worker, "rc", side_effect=fake_rc):
                copied, failed = worker.upload_partial_artifacts(
                    "cline-bridge",
                    {"artifacts": [
                        "packs/cline-bridge/../../secrets.env",
                    ]},
                    td,
                    "gdrive:pilot",
                )

            self.assertEqual(copied, [])
            self.assertEqual(failed, [])
            self.assertEqual(calls, [])

    def test_run_sh_failure_uploads_declared_artifact_but_stays_failed(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            code = (
                "import os,pathlib,sys; "
                "p=pathlib.Path(os.environ['PACK_DIR'])/'out/task-result.json'; "
                "p.parent.mkdir(parents=True,exist_ok=True); "
                "p.write_text('{\\\"result\\\":\\\"failed\\\"}'); sys.exit(7)"
            )
            command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
            spec = {
                "run_sh": command,
                "timeout_s": 10,
                "artifacts": [
                    "packs/cline-bridge/out/task-result.json",
                    "packs/cline-bridge/out/task.patch",
                ],
            }

            def fake_rc(*args, **kwargs):
                calls.append(args)
                if args[0] == "copy":
                    out = Path(args[2]) / "out"
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "task-result.json").write_text(
                        '{"result":"stale"}')
                    (out / "task.patch").write_text("stale patch")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(worker, "rc", side_effect=fake_rc), \
                    patch.object(worker, "WORKDIR", td):
                ok, info = worker.run_pack(
                    "cline-bridge", spec, "gdrive:pilot")

            self.assertFalse(ok)
            self.assertIn("run_sh rc=7", info)
            self.assertIn("preserved 1 declared partial artifact", info)
            self.assertTrue(any(call[0] == "copyto" for call in calls))
            self.assertFalse(any(
                call[0] == "copy"
                and call[1] == f"{td}/cline-bridge"
                for call in calls
            ))
            local_out = Path(td) / "cline-bridge" / "out"
            self.assertEqual(
                (local_out / "task-result.json").read_text(),
                '{"result":"failed"}')
            self.assertFalse((local_out / "task.patch").exists())


if __name__ == "__main__":
    unittest.main()
