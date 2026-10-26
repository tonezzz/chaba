"""Sandbox tests for the ada-nest job console — the two operator cells,
the warmup overlap contract, and an end-to-end runner drain.

Covers the card's test list:
  - CPU / no-Drive preflight refuses queue start
  - fresh T4 preflight passes
  - duplicate managed T4 session blocks, naming the peer identity
  - runner PID/lease never kills another VM by PID collision
  - warmup keeps running while the cache-restore prep is pending
  - queued packs drain in the same VM afterwards
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COLAB = REPO / "scripts/colab"
LAUNCHER = COLAB / "queue-launcher-cell.py"
PREFLIGHT = COLAB / "preflight-cell.py"
REGISTRY = COLAB / "runtime_registry.py"
RUNNER = COLAB / "queue-runner.py"
JOBS_SRC = COLAB / "JOBS.py"
BUILD_NB = COLAB / "build-job-console.py"

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


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


class ConsoleSandbox(unittest.TestCase):
    with_gpu = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nest-console-"))
        self.root = self.tmp / "ada-nest"
        self.q = self.root / "queue"
        (self.q / "runtime-sessions").mkdir(parents=True)
        (self.root / "packs").mkdir()
        shutil.copy(REGISTRY, self.q / "runtime_registry.py")
        shutil.copy(RUNNER, self.q / "runner.py")
        self.old_env = {k: os.environ.get(k) for k in
                        ("NEST_ROOT", "NEST_QUEUE", "NEST_RUNTIME_TTL_S",
                         "PATH", "WARMUP_MIN_S", "WARMUP_MAX_S",
                         "NEST_QUEUE_SETTLE_S")}
        os.environ["NEST_ROOT"] = str(self.root)
        os.environ["NEST_QUEUE"] = str(self.q)
        os.environ["NEST_RUNTIME_TTL_S"] = "60"
        os.environ["NEST_QUEUE_SETTLE_S"] = "0.2"
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        smi = self.bindir / "nvidia-smi"
        smi.write_text(NVIDIA_SMI_STUB if self.with_gpu
                       else "#!/bin/bash\nexit 1\n")
        smi.chmod(smi.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP
                  | stat.S_IXOTH)
        os.environ["PATH"] = f"{self.bindir}:{os.environ['PATH']}"
        self.launcher = load_module(LAUNCHER, "queue_launcher_cell")

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def write_peer(self, boot, age_s=0.0):
        rec = {"boot_id": boot, "kind": "managed-notebook",
               "gpu": "Tesla T4", "gpu_gb": 15.36, "ram_gb": 12.6,
               "drive_mounted": True, "registered_at": time.time() - age_s,
               "ts": time.time() - age_s}
        (self.q / "runtime-sessions" / f"{boot}.json").write_text(json.dumps(rec))

    def write_runner_id(self, boot, pid, age_s=0.0):
        (self.q / "runner.id").write_text(json.dumps(
            {"pid": pid, "boot_id": boot, "worker": f"colab-{boot[:8]}-{pid}",
             "epoch": 3, "ts": time.time() - age_s}))

    def write_heartbeat(self, age_s=0.0):
        (self.q / "heartbeat").write_text(
            f"{time.time() - age_s:.0f} some-job run\n")

    def spawn_sleeper(self):
        p = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: p.poll() is None and p.kill())
        return p


class TestPreflightCell(ConsoleSandbox):
    def test_preflight_registers_and_passes_fresh_t4(self):
        pc = load_module(PREFLIGHT, "preflight_cell")
        pc.HB_S = 9999                      # don't let the hb thread fire
        pc.main()                           # must not raise
        rec = json.loads(next(
            (self.q / "runtime-sessions").glob("*.json")).read_text())
        self.assertEqual(rec["gpu"], "Tesla T4")
        self.assertEqual(rec["boot_id"], boot_id())

    def test_preflight_duplicate_blocks_with_identity(self):
        self.write_peer("peer-other-d2d2", age_s=3)
        pc = load_module(PREFLIGHT, "preflight_cell")
        pc.HB_S = 9999
        with self.assertRaises(SystemExit) as cm:
            pc.main()
        self.assertIn("peer-other-d2d2"[:8], str(cm.exception))
        self.assertFalse(
            (self.q / "runtime-sessions" / f"{boot_id()}.json").exists(),
            "a refused preflight must not leave a fresh runtime heartbeat")


class TestControlRequests(ConsoleSandbox):
    def write_control_request(self, request_id, target_boot_id, age_s=0,
                              command="start_queue", confirmed=True):
        request_dir = self.q / "control" / "requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        path = request_dir / f"{request_id}.json"
        path.write_text(json.dumps({
            "request_id": request_id,
            "target_boot_id": target_boot_id,
            "command": command,
            "confirmed": confirmed,
            "created_at": time.time() - age_s,
        }))
        return path

    def test_matching_start_request_launches_once_and_acks(self):
        pc = load_module(PREFLIGHT, "preflight_control")
        calls = []

        def launch():
            calls.append("start")
            print("queue pid 123")

        req = self.write_control_request("req-a1", boot_id())
        result = pc.process_control_request(
            str(req), boot_id(), queue_dir=str(self.q),
            launcher_main=launch)
        self.assertEqual(result["status"], "started")
        self.assertEqual(calls, ["start"])
        ack = json.loads(
            (self.q / "control" / "acks" / "req-a1.json").read_text())
        self.assertEqual(ack["status"], "started")

        again = pc.process_control_request(
            str(req), boot_id(), queue_dir=str(self.q),
            launcher_main=launch)
        self.assertEqual(again["status"], "already-acked")
        self.assertEqual(calls, ["start"])

    def test_foreign_boot_request_is_not_consumed(self):
        pc = load_module(PREFLIGHT, "preflight_control")
        req = self.write_control_request("req-b2", "another-boot")
        calls = []
        result = pc.process_control_request(
            str(req), boot_id(), queue_dir=str(self.q),
            launcher_main=lambda: calls.append("start"))
        self.assertEqual(result["status"], "not-targeted")
        self.assertEqual(calls, [])
        self.assertFalse((self.q / "control" / "acks" / "req-b2.json").exists())

    def test_expired_request_is_acked_without_launch(self):
        pc = load_module(PREFLIGHT, "preflight_control")
        req = self.write_control_request(
            "req-c3", boot_id(), age_s=pc.CONTROL_TTL_S + 1)
        calls = []
        result = pc.process_control_request(
            str(req), boot_id(), queue_dir=str(self.q),
            launcher_main=lambda: calls.append("start"))
        self.assertEqual(result["status"], "expired")
        self.assertEqual(calls, [])
        ack = json.loads(
            (self.q / "control" / "acks" / "req-c3.json").read_text())
        self.assertEqual(ack["status"], "expired")

    def test_unconfirmed_request_is_rejected(self):
        pc = load_module(PREFLIGHT, "preflight_control")
        req = self.write_control_request(
            "req-d4", boot_id(), confirmed=False)
        calls = []
        result = pc.process_control_request(
            str(req), boot_id(), queue_dir=str(self.q),
            launcher_main=lambda: calls.append("start"))
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(calls, [])


class TestLaunchGate(ConsoleSandbox):
    def test_fresh_t4_passes_and_spawns(self):
        spawned = []
        self.launcher.spawn = lambda q: spawned.append(q)
        self.launcher.main()
        self.assertEqual(spawned, [str(self.q)])

    def test_duplicate_managed_runtime_blocks_with_identity(self):
        self.write_peer("peer-dupe-e3e3", age_s=1)
        with self.assertRaises(SystemExit) as cm:
            self.launcher.main()
        self.assertIn("peer-dupe-e3e3"[:8], str(cm.exception))

    def test_same_vm_live_runner_reports_not_respawns(self):
        sleeper = self.spawn_sleeper()
        self.write_runner_id(boot_id(), sleeper.pid)
        self.write_heartbeat(age_s=5)
        state, _ = self.launcher.runner_state(str(self.q))
        self.assertEqual(state, "alive-local")
        spawned = []
        self.launcher.spawn = lambda q: spawned.append(q)
        self.launcher.main()
        self.assertEqual(spawned, [])


class TestPidCollisionSafety(ConsoleSandbox):
    """A Drive-visible pid is never a process handle for another VM."""

    def test_foreign_pid_never_signaled(self):
        sleeper = self.spawn_sleeper()          # a REAL live local pid
        self.write_runner_id("foreign-boot-f4f4", sleeper.pid)
        # fresh heartbeat -> another VM's queue is alive -> refuse, no kill
        self.write_heartbeat(age_s=5)
        kills = []
        orig_kill = os.kill
        self.launcher.os.kill = lambda p, s: kills.append((p, s))
        try:
            state, detail = self.launcher.runner_state(str(self.q))
            self.assertEqual(state, "alive-elsewhere")
            self.assertIn("foreign-boot-f4f4"[:8], detail)
            self.assertIn(str(sleeper.pid), detail)   # identity, not a handle
            with self.assertRaises(SystemExit):
                self.launcher.main()
        finally:
            self.launcher.os.kill = orig_kill
        self.assertNotIn(sleeper.pid, [p for p, _ in kills])
        self.assertIsNone(sleeper.poll())       # still alive

    def test_stale_foreign_record_left_alone(self):
        self.write_runner_id("foreign-boot-a5a5", 424242)
        # no heartbeat at all -> stale record -> free, and never signaled
        kills = []
        orig_kill = os.kill
        self.launcher.os.kill = lambda p, s: kills.append((p, s))
        try:
            state, detail = self.launcher.runner_state(str(self.q))
            self.assertEqual(state, "free")
            self.assertIn("never signaling", detail)
        finally:
            self.launcher.os.kill = orig_kill
        self.assertNotIn(424242, [p for p, _ in kills])

    def test_same_vm_zombie_reaped(self):
        sleeper = self.spawn_sleeper()
        self.write_runner_id(boot_id(), sleeper.pid)
        self.write_heartbeat(age_s=9999)        # stale: kernel survived restart
        state, _ = self.launcher.runner_state(str(self.q))
        self.assertEqual(state, "zombie-local")
        spawned = []
        self.launcher.spawn = lambda q: spawned.append(q)
        self.launcher.main()
        self.assertEqual(spawned, [str(self.q)])
        for _ in range(50):
            if sleeper.poll() is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(sleeper.poll())    # zombie actually reaped


class TestLaunchGateNegative(ConsoleSandbox):
    def test_no_drive_refuses(self):
        os.environ["NEST_QUEUE"] = str(self.tmp / "no-such-queue")
        os.environ["NEST_ROOT"] = str(self.tmp / "no-such-root")
        with self.assertRaises(SystemExit) as cm:
            self.launcher.main()
        self.assertIn("REFUSED", str(cm.exception))


class TestLaunchGateCpu(ConsoleSandbox):
    with_gpu = False

    def test_cpu_runtime_refuses_queue_start(self):
        with self.assertRaises(SystemExit) as cm:
            self.launcher.main()
        self.assertIn("GPU", str(cm.exception))


class TestWarmupOverlap(ConsoleSandbox):
    """The warmup run-source keeps working until QUEUE_PENDING exits."""

    def warmup_src(self):
        mod = load_module(JOBS_SRC, "nest_jobs")
        job = next(j for j in mod.JOBS if j["name"] == "t4-session-warmup")
        self.assertEqual(job["scope"], "env")
        return job["run"]

    def exec_warmup(self, pending, min_s, max_s):
        os.environ["WARMUP_MIN_S"] = str(min_s)
        os.environ["WARMUP_MAX_S"] = str(max_s)
        ns = {"QUEUE_PENDING": pending, "BOOT_ID": boot_id(),
              "NEST_ROOT": str(self.root)}
        t0 = time.time()
        exec(compile(self.warmup_src(), "<warmup>", "exec"), ns)
        return time.time() - t0

    def test_warmup_runs_while_prep_pending(self):
        prep = subprocess.Popen(["sleep", "1.0"])
        dt = self.exec_warmup(("restore-hf-cache", None, prep), 0.05, 10)
        self.assertGreaterEqual(dt, 0.7)
        self.assertLess(dt, 9)
        stats = json.loads(
            (self.q / "warmup" / f"{boot_id()}.json").read_text())
        self.assertEqual(stats["waited_for_prep"], "restore-hf-cache")

    def test_warmup_min_floor_when_no_pending(self):
        dt = self.exec_warmup(None, 0.5, 10)
        self.assertGreaterEqual(dt, 0.45)

    def test_warmup_cap_when_prep_hangs(self):
        prep = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: prep.poll() is None and prep.kill())
        dt = self.exec_warmup(("restore-hf-cache", None, prep), 0.05, 0.5)
        self.assertLess(dt, 5)


class TestEndToEndDrain(ConsoleSandbox):
    """Real runner.py against a sandbox nest: env jobs then packs, one VM."""

    def write_pack(self, name):
        d = self.root / "packs" / name
        d.mkdir(parents=True)
        (d / "pack.yml").write_text(
            f"name: {name}\n"
            "needs:\n"
            "  egress_only_ok: true\n"
            "timeout_s: 60\n"
            "artifacts:\n"
            f"  - packs/{name}/out/result.txt\n"
            "run: |\n"
            "  import os\n"
            "  os.makedirs(f'{PACK_DIR}/out', exist_ok=True)\n"
            "  open(f'{PACK_DIR}/out/result.txt','w').write('ok\\n')\n")

    def run_runner(self, mutate=None):
        # write a JOBS.py reusing the real warmup source verbatim
        jobs_mod = load_module(JOBS_SRC, "nest_jobs_it")
        warmup = next(j for j in jobs_mod.JOBS
                      if j["name"] == "t4-session-warmup")
        (self.q / "JOBS.py").write_text(
            "JOBS = [\n"
            f" {warmup!r},\n"
            " {'name': 'env-prep', 'scope': 'env',\n"
            "  'prep': 'sleep 1.0',\n"
            "  'run': 'print(\"env prep done\")'},\n"
            "]\n")
        self.write_pack("voice-smoke")
        self.write_pack("devnest-smoke")
        env = dict(os.environ, WARMUP_MIN_S="0.05", WARMUP_MAX_S="20")
        proc = subprocess.Popen(
            [sys.executable, "-u", str(RUNNER)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env)
        if mutate:
            deadline = time.time() + 10
            while time.time() < deadline:
                if (self.q / "heartbeat").exists():
                    time.sleep(0.1)
                    mutate()
                    break
                time.sleep(0.05)
        out, _ = proc.communicate(timeout=120)
        return proc.returncode, out

    def test_env_then_packs_drain_in_one_vm(self):
        rc, out = self.run_runner()
        self.assertEqual(rc, 0, out)
        boot = boot_id()
        # env-scoped markers landed under this boot
        for job in ("t4-session-warmup", "env-prep"):
            self.assertTrue(
                (self.q / "env-done" / boot / f"{job}.done").exists(), job)
        # warmup waited for the 1.0s env-prep sleep
        mark = (self.q / "env-done" / boot
                / "t4-session-warmup.done").read_text()
        self.assertGreaterEqual(float(mark.split("s")[0]), 0.7)
        # packs ran in the same VM — same boot stamped in their markers
        for pack in ("voice-smoke", "devnest-smoke"):
            done = self.root / "packs" / pack / "done"
            self.assertTrue(done.exists(), pack)
            self.assertIn(f"boot={boot}", done.read_text())
            self.assertTrue(
                (self.root / "packs" / pack / "out" / "result.txt").exists())
        # clean exit removed our identity files
        self.assertFalse((self.q / "runner.id").exists())
        self.assertFalse((self.q / "runner.pid").exists())
        self.assertTrue((self.q / "heartbeat").exists())

    def test_foreign_runner_id_survives_our_exit(self):
        """If a newer generation's runner.id appeared mid-run, our cleanup
        must NOT delete it — that would strip the live runner's identity."""
        def plant_foreign():
            (self.q / "runner.id").write_text(json.dumps(
                {"pid": 31337, "boot_id": "other-boot-b6b6",
                 "worker": "colab-other-b6b6-31337", "epoch": 99,
                 "ts": int(time.time())}))
            (self.q / "runner.pid").write_text("31337")
        rc, out = self.run_runner(mutate=plant_foreign)
        self.assertEqual(rc, 0, out)
        rid = json.loads((self.q / "runner.id").read_text())
        self.assertEqual(rid["boot_id"], "other-boot-b6b6")
        self.assertEqual((self.q / "runner.pid").read_text(), "31337")


class TestNotebookFreshness(unittest.TestCase):
    def test_console_notebook_in_sync_with_cells(self):
        r = subprocess.run([sys.executable, str(BUILD_NB), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
