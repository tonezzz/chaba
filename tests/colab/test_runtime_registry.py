"""Sandbox tests for scripts/colab/runtime_registry.py — the ada-nest
managed-runtime registry behind the job console's session guard.

Covers: record identity fields, register/heartbeat + peer freshness TTL,
and the launch-gate matrix (no Drive, no GPU, fresh duplicate, override).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "scripts/colab/runtime_registry.py"
RUNNER_SRC = REPO / "scripts/colab/queue-runner.py"

NVIDIA_SMI_STUB = """#!/bin/bash
case "$*" in
  *"name,memory.total"*) echo "Tesla T4, 15360" ;;
  *"memory.total"*)      echo "15360" ;;
  *"memory.free"*)       echo "15000" ;;
  *"utilization.gpu,memory.used"*) echo "0, 0" ;;
  *) echo "0" ;;
esac
exit 0
"""


def load_registry():
    spec = importlib.util.spec_from_file_location(
        "runtime_registry", REGISTRY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Sandbox(unittest.TestCase):
    """Fresh ada-nest tree + env; with_gpu controls the nvidia-smi stub."""

    with_gpu = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nest-reg-"))
        self.root = self.tmp / "ada-nest"
        self.q = self.root / "queue"
        (self.q / "runtime-sessions").mkdir(parents=True)
        (self.root / "packs").mkdir()
        # mirror the Drive deployment layout: registry + runner in queue/
        shutil.copy(REGISTRY, self.q / "runtime_registry.py")
        shutil.copy(RUNNER_SRC, self.q / "runner.py")
        self.old_env = {k: os.environ.get(k) for k in
                        ("NEST_ROOT", "NEST_QUEUE", "NEST_RUNTIME_TTL_S",
                         "PATH")}
        os.environ["NEST_ROOT"] = str(self.root)
        os.environ["NEST_QUEUE"] = str(self.q)
        os.environ["NEST_RUNTIME_TTL_S"] = "60"
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        smi = self.bindir / "nvidia-smi"
        # stub always shadows any real host binary: GPU stub answers, CPU
        # stub exits 1 (no driver) so tests are host-independent
        smi.write_text(NVIDIA_SMI_STUB if self.with_gpu
                       else "#!/bin/bash\nexit 1\n")
        smi.chmod(smi.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP
                  | stat.S_IXOTH)
        os.environ["PATH"] = f"{self.bindir}:{os.environ['PATH']}"
        self.rr = load_registry()

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_peer(self, boot, age_s=0.0, gpu="Tesla T4", gpu_gb=15.36):
        rec = {"boot_id": boot, "kind": "managed-notebook", "gpu": gpu,
               "gpu_gb": gpu_gb, "ram_gb": 12.6, "drive_mounted": True,
               "registered_at": time.time() - age_s,
               "ts": time.time() - age_s}
        p = self.q / "runtime-sessions" / f"{boot}.json"
        p.write_text(json.dumps(rec) + "\n")
        return rec


class TestRegisterAndIdentity(Sandbox):
    def test_register_writes_identity_record(self):
        rec = self.rr.register()
        self.assertEqual(rec["boot_id"], self.rr.boot_id())
        self.assertEqual(rec["gpu"], "Tesla T4")
        self.assertAlmostEqual(rec["gpu_gb"], 15.0, places=0)
        self.assertGreater(rec["ram_gb"], 0)
        self.assertTrue(rec["drive_mounted"])
        on_disk = json.loads(
            (self.q / "runtime-sessions" / f"{rec['boot_id']}.json").read_text())
        self.assertEqual(on_disk["kind"], "managed-notebook")
        # re-register preserves the original registered_at
        time.sleep(0.02)
        rec2 = self.rr.register()
        self.assertEqual(rec2["registered_at"], rec["registered_at"])
        self.assertGreaterEqual(rec2["ts"], rec["ts"])


class TestPeerFreshness(Sandbox):
    def test_fresh_peer_listed_stale_peer_not(self):
        self.rr.register()
        self.write_peer("peer-live-aaaa", age_s=5)
        self.write_peer("peer-dead-bbbb", age_s=3600)
        fresh = self.rr.peers()
        self.assertEqual([p["boot_id"] for p in fresh], ["peer-live-aaaa"])
        stale = self.rr.stale()
        self.assertEqual([p["boot_id"] for p in stale], ["peer-dead-bbbb"])
        # corrupt record is ignored, not fatal
        (self.q / "runtime-sessions" / "garbage.json").write_text("{not json")
        self.assertEqual(len(self.rr.peers()), 1)


class TestLaunchGate(Sandbox):
    def test_gate_matrix(self):
        # fresh T4, no peers -> go
        self.assertEqual(self.rr.launch_gate(), [])
        # fresh peer -> refuse, and the refusal names the peer's boot id
        peer = self.write_peer("peer-dupe-c1c1", age_s=2)
        probs = self.rr.launch_gate()
        self.assertTrue(any("peer-dupe-c1c1"[:8] in p for p in probs), probs)
        # explicit override clears ONLY the duplicate leg
        self.assertEqual(self.rr.launch_gate(allow_second=True), [])
        # peer stale -> go again
        self.write_peer("peer-dupe-c1c1", age_s=3600)
        self.assertEqual(self.rr.launch_gate(), [])


class TestLaunchGateNoDrive(unittest.TestCase):
    def test_missing_root_refuses(self):
        old = os.environ.get("NEST_ROOT")
        os.environ["NEST_ROOT"] = "/nonexistent-nest-root-xyz"
        try:
            rr = load_registry()
            probs = rr.launch_gate()
            self.assertTrue(any("Drive" in p or "runner.py" in p
                                for p in probs), probs)
        finally:
            if old is None:
                os.environ.pop("NEST_ROOT", None)
            else:
                os.environ["NEST_ROOT"] = old


class TestLaunchGateCpu(Sandbox):
    """CPU runtime (no nvidia-smi) must refuse queue start."""

    with_gpu = False

    def test_cpu_refuses(self):
        name, gb = self.rr.gpu_info()
        self.assertEqual((name, gb), ("", 0.0))
        probs = self.rr.launch_gate()
        self.assertTrue(any("GPU" in p for p in probs), probs)


if __name__ == "__main__":
    unittest.main()
