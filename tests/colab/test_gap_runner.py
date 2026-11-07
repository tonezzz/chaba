"""Sandbox tests for scripts/colab/gap-runner.py — the ada-nest gap runner.

Runs the REAL runner module against a fake ada-nest tree in a temp dir:
  - queue/heartbeat is a file the test rewrites to simulate main-queue phases
  - nvidia-smi is a stub on PATH reporting a configurable free-VRAM figure
  - ollama is a mock HTTP server on 127.0.0.1:11434 serving /api/tags and
    /api/embed (embedding-smoke hits the real endpoint path)

Covers the card's gate contract: fresh prep/prep-wait window, VRAM gate,
single gap lease, mid-run abort, forbidden-pattern scan, no-pull guard,
verify-before-mark, done/failed markers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "scripts/colab/gap-runner.py"
PACK_SRC = REPO / "scripts/colab/gap-packs/embedding-smoke/pack.json"


def load_runner(nest_root: Path):
    os.environ["NEST_ROOT"] = str(nest_root)
    spec = importlib.util.spec_from_file_location("gap_runner", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SETTLE_S = 0.05
    mod.POLL_S = 0.2
    return mod


class MockOllama(BaseHTTPRequestHandler):
    models = ["nomic-embed-text:latest"]
    embed_delay = 0.0
    embed_calls = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/tags":
            body = json.dumps(
                {"models": [{"name": m} for m in self.models]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/embed":
            type(self).embed_calls += 1
            time.sleep(type(self).embed_delay)
            n = len(json.loads(self.rfile.read(
                int(self.headers["Content-Length"]))).get("input", []))
            body = json.dumps(
                {"embeddings": [[0.1] * 768] * n}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class GapRunnerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin_dir = Path(tempfile.mkdtemp(prefix="gap-bin-"))
        smi = cls.bin_dir / "nvidia-smi"
        smi.write_text(
            "#!/bin/sh\n"
            "if echo \"$*\" | grep -q memory.free; then\n"
            "  cat \"${FAKE_VRAM_FREE_FILE:-/dev/null}\" 2>/dev/null || echo 8000\n"
            "else\n"
            "  echo 'FakeGPU, 8000, 15360'\nfi\n")
        smi.chmod(smi.stat().st_mode | stat.S_IEXEC)
        cls.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{cls.bin_dir}:{cls.old_path}"

        try:
            cls.httpd = HTTPServer(("127.0.0.1", 11434), MockOllama)
        except OSError as exc:
            raise unittest.SkipTest(
                f"cannot mock ollama on :11434 ({exc}) — a real service "
                "holds the port; run on a host without a live ollama"
            ) from exc
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        os.environ["PATH"] = cls.old_path
        shutil.rmtree(cls.bin_dir, ignore_errors=True)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="gap-nest-"))
        (self.root / "queue").mkdir(parents=True)
        (self.root / "gap-packs").mkdir()
        self.pack = self.root / "gap-packs/embedding-smoke"
        self.pack.mkdir(parents=True)
        shutil.copy(PACK_SRC, self.pack / "pack.json")
        self.vram_file = self.root / "vram_free"
        self.vram_file.write_text("8000")
        self.old_vram_env = os.environ.get("FAKE_VRAM_FREE_FILE")
        os.environ["FAKE_VRAM_FREE_FILE"] = str(self.vram_file)
        MockOllama.models = ["nomic-embed-text:latest"]
        MockOllama.embed_delay = 0.0
        MockOllama.embed_calls = 0
        self.gr = load_runner(self.root)

    def tearDown(self):
        if self.old_vram_env is None:
            os.environ.pop("FAKE_VRAM_FREE_FILE", None)
        else:
            os.environ["FAKE_VRAM_FREE_FILE"] = self.old_vram_env
        shutil.rmtree(self.root, ignore_errors=True)

    def beat(self, phase="prep", age=0.0, job="main-job"):
        (self.root / "queue/heartbeat").write_text(
            f"{time.time() - age:.0f} {job} {phase}\n")

    def output(self, fn) -> str:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn()
        return buf.getvalue()

    # --- gate tests -------------------------------------------------------

    def test_stale_heartbeat_blocks(self):
        self.beat("prep", age=300)
        out = self.output(self.gr.main)
        self.assertIn("stale", out)
        self.assertFalse((self.pack / "done").exists())
        self.assertEqual(MockOllama.embed_calls, 0)

    def test_run_phase_blocks(self):
        self.beat("run")
        out = self.output(self.gr.main)
        self.assertIn("phase run", out)
        self.assertFalse((self.pack / "done").exists())

    def test_vram_gate_blocks(self):
        self.beat("prep")
        self.vram_file.write_text("100")  # 100MiB < 1GB floor
        out = self.output(self.gr.main)
        self.assertIn("vram", out)
        self.assertFalse((self.pack / "done").exists())

    def test_other_gap_lease_blocks(self):
        self.beat("prep")
        (self.root / "queue/gap-lease").write_text(json.dumps(
            {"worker": "gap-other-999", "pid": 1, "ts": time.time()}))
        out = self.output(self.gr.main)
        self.assertIn("held by gap-other-999", out)
        self.assertFalse((self.pack / "done").exists())

    def test_forbidden_pattern_skips(self):
        spec = json.loads((self.pack / "pack.json").read_text())
        spec["run"] = "ollama pull nomic-embed-text\n" + spec["run"]
        (self.pack / "pack.json").write_text(json.dumps(spec))
        self.beat("prep")
        out = self.output(self.gr.main)
        self.assertIn("forbidden", out)
        self.assertFalse((self.pack / "done").exists())
        self.assertEqual(MockOllama.embed_calls, 0)

    def test_missing_model_no_pull(self):
        MockOllama.models = ["some-other-model:latest"]
        self.beat("prep")
        self.output(self.gr.main)
        self.assertEqual(MockOllama.embed_calls, 0)
        self.assertFalse((self.pack / "done").exists())
        self.assertTrue((self.pack / "failed").exists())
        log = (self.pack / "out/gap.log").read_text()
        self.assertIn("refusing to pull", log)

    # --- happy path -------------------------------------------------------

    def test_end_to_end_done(self):
        self.beat("prep")
        out = self.output(self.gr.main)
        self.assertIn("DONE", out)
        self.assertTrue((self.pack / "done").is_file())
        art = json.loads(
            (self.pack / "out/embedding-smoke.json").read_text())
        self.assertEqual(art["documents"], 10)
        self.assertEqual(art["dimensions"], 768)
        self.assertEqual(MockOllama.embed_calls, 1)
        # lease released, gap-heartbeat written, claim dir empty
        self.assertFalse((self.root / "queue/gap-lease").exists())
        self.assertTrue((self.root / "queue/gap-heartbeat").exists())
        self.assertEqual(list((self.pack / "claim").iterdir()), [])
        # second pass skips the done pack without touching ollama
        out2 = self.output(self.gr.main)
        self.assertNotIn("embedding-smoke: run", out2)
        self.assertEqual(MockOllama.embed_calls, 1)

    def test_prep_wait_phase_also_opens_window(self):
        self.beat("prep-wait")
        out = self.output(self.gr.main)
        self.assertIn("DONE", out)

    # --- mid-run abort ----------------------------------------------------

    def test_abort_when_main_reclaims_gpu(self):
        slow = self.root / "gap-packs/slow-pack"
        (slow / "out").mkdir(parents=True)
        (slow / "pack.json").write_text(json.dumps({
            "name": "slow-pack", "min_free_gpu_gb": 0, "timeout_s": 60,
            "run": "sleep 30"}))
        self.beat("prep")
        done_flag = {}

        def flip():
            time.sleep(1.0)
            self.beat("run")          # main queue wants the GPU back
            done_flag["flipped"] = True

        threading.Thread(target=flip, daemon=True).start()
        t0 = time.time()
        out = self.output(self.gr.main)
        dt = time.time() - t0
        self.assertLess(dt, 20)                    # didn't wait out sleep 30
        self.assertIn("ABORT", out.upper())
        self.assertFalse((slow / "done").exists())
        self.assertFalse((slow / "failed").exists())   # retry next window
        self.assertEqual(list((slow / "claim").iterdir()), [])
        self.assertTrue((slow / "out/aborted.txt").exists())


if __name__ == "__main__":
    unittest.main()
