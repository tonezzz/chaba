"""Unit tests for runner-agent.py interactive-host guards
(card omen-gpu-display-wedge): task unit props, the gpu VRAM
pre-flight, and the presentation-watchdog state machine.

Imports the dash-named module via importlib; every system probe
(sh, unit_active, gpu_free_mb, display_stalled, api) is monkeypatched
— no systemd, nvidia-smi, or X needed.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


class TaskPropsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        m.LIMITS_ON = True
        m.TASK_NICE = 10
        m.TASK_CPU_QUOTA = "500%"
        m.TASK_MEM_MAX = "12G"
        m.TASK_CPU_WEIGHT = "50"
        m.TASK_IO_WEIGHT = "50"
        m.TASK_IO_CLASS = "best-effort"
        m.TASK_IO_PRIO = "6"

    def test_props_empty_when_limits_off(self):
        self.mod.LIMITS_ON = False
        self.assertEqual(self.mod.task_run_props(), [])

    def test_props_cover_nice_quota_mem_io(self):
        props = " ".join(self.mod.task_run_props())
        self.assertIn("--property=Nice=10", props)
        self.assertIn("--property=CPUQuota=500%", props)
        self.assertIn("--property=MemoryMax=12G", props)
        self.assertIn("--property=CPUWeight=50", props)
        self.assertIn("--property=IOWeight=50", props)
        self.assertIn("--property=IOSchedulingClass=best-effort", props)
        self.assertIn("--property=IOSchedulingPriority=6", props)

    def test_default_quota_leaves_headroom(self):
        self.mod.TASK_CPU_QUOTA = ""
        import os
        expect = f"{max(100, (os.cpu_count() or 2) * 75)}%"
        self.assertEqual(self.mod.task_cpu_quota(), expect)

    def test_io_class_none_skips_ionice_props(self):
        self.mod.TASK_IO_CLASS = "none"
        props = " ".join(self.mod.task_run_props())
        self.assertNotIn("IOSchedulingClass", props)


class GpuPreflightTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        self.mod.GPU_MIN_FREE_MB = 512
        self._probe = self.mod.gpu_free_mb

    def tearDown(self):
        self.mod.gpu_free_mb = self._probe

    def _card(self, **action):
        action.setdefault("labels", ["gpu"])
        return {"id": "c1", "action": action}

    def test_need_parsed_from_gpu_dict(self):
        c = self._card(gpu={"min_free_mb": 3000})
        self.assertEqual(self.mod.card_gpu_need_mb(c), 3000)

    def test_need_parsed_from_bare_int_and_scalars(self):
        self.assertEqual(self.mod.card_gpu_need_mb(
            self._card(gpu=2500)), 2500)
        self.assertEqual(self.mod.card_gpu_need_mb(
            self._card(min_vram_mb=1800)), 1800)
        self.assertEqual(self.mod.card_gpu_need_mb(self._card()), 0)

    def test_non_gpu_card_passes(self):
        c = {"id": "c2", "action": {"labels": ["ssd"]}}
        self.assertEqual(self.mod.gpu_preflight(c), "")

    def test_defer_when_free_below_need(self):
        self.mod.gpu_free_mb = lambda: (1000, 4096)
        c = self._card(gpu={"min_free_mb": 3000})
        r = self.mod.gpu_preflight(c)
        self.assertIn("deferred", r)
        self.assertIn("1000MB", r)

    def test_host_floor_defers_even_without_card_need(self):
        self.mod.gpu_free_mb = lambda: (300, 4096)
        r = self.mod.gpu_preflight(self._card())
        self.assertIn("deferred", r)
        self.assertIn("512MB", r)

    def test_refuse_when_need_exceeds_total(self):
        self.mod.gpu_free_mb = lambda: (4000, 4096)
        c = self._card(gpu={"min_free_mb": 8000})
        r = self.mod.gpu_preflight(c)
        self.assertIn("never fit", r)

    def test_ok_when_free_covers_need(self):
        self.mod.gpu_free_mb = lambda: (3500, 4096)
        c = self._card(gpu={"min_free_mb": 3000})
        self.assertEqual(self.mod.gpu_preflight(c), "")

    def test_no_nvidia_smi_blocks_gpu_cards(self):
        self.mod.gpu_free_mb = lambda: None
        r = self.mod.gpu_preflight(self._card())
        self.assertIn("nvidia-smi", r)


class WatchdogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        m.WD_ON = True
        m.WD_STRIKES = 2
        m.WD_HEALTHY = 2
        m.WD_CPU_QUOTA = "30%"
        m.WD_NICE = 19
        m.LIMITS_ON = False
        self.sh_calls = []
        self.comments = []
        self._saved = (m.sh, m.unit_active, m.display_stalled,
                       m.api, m.renice_unit)
        m.sh = lambda cmd, **kw: (self.sh_calls.append(cmd), _proc())[1]
        m.api = lambda path, body=None: (
            self.comments.append(body or {}), {})[1]
        m.renice_unit = lambda unit, nice: self.sh_calls.append(
            ["renice", "-n", str(nice), unit])
        m.unit_active = lambda u: True
        m.display_stalled = lambda: (False, "")

    def tearDown(self):
        (self.mod.sh, self.mod.unit_active, self.mod.display_stalled,
         self.mod.api, self.mod.renice_unit) = self._saved

    def _state(self):
        return {"c1": {"unit": "devin-task-x", "type": "dispatch",
                       "gpu": True}}

    def test_no_gpu_entries_is_noop(self):
        st = {"c2": {"unit": "u", "type": "script"}}
        self.assertFalse(self.mod.watchdog_pass(st))
        self.assertEqual(self.sh_calls, [])

    def test_stall_deprioritizes_then_pauses(self):
        self.mod.display_stalled = lambda: (True, "vsync flood")
        st = self._state()
        self.mod.watchdog_pass(st)   # strike 1
        self.assertFalse(st["c1"]["wd"].get("paused"))
        flat = [str(c) for c in self.sh_calls]
        self.assertTrue(any("CPUQuota=30%" in c for c in flat))
        self.assertTrue(any("renice" in c for c in flat))
        self.assertTrue(any("deprioritized" in c.get("text", "")
                            for c in self.comments))
        self.mod.watchdog_pass(st)   # strike 2 -> pause
        self.assertTrue(st["c1"]["wd"]["paused"])
        flat = [str(c) for c in self.sh_calls]
        self.assertTrue(any("SIGSTOP" in c for c in flat))
        self.assertTrue(any("chvt 3" in c.get("text", "")
                            for c in self.comments))

    def test_healthy_probes_resume_paused_task(self):
        st = self._state()
        st["c1"]["wd"] = {"paused": True, "strikes": 0, "healthy": 0}
        self.mod.watchdog_pass(st)   # healthy 1
        self.assertTrue(st["c1"]["wd"]["paused"])
        self.mod.watchdog_pass(st)   # healthy 2 -> SIGCONT
        self.assertFalse(st["c1"]["wd"]["paused"])
        flat = [str(c) for c in self.sh_calls]
        self.assertTrue(any("SIGCONT" in c for c in flat))
        self.assertTrue(any("resumed" in c.get("text", "")
                            for c in self.comments))

    def test_healthy_resets_strikes(self):
        st = self._state()
        st["c1"]["wd"] = {"strikes": 1}
        self.mod.watchdog_pass(st)
        self.assertEqual(st["c1"]["wd"]["strikes"], 0)

    def test_display_stalled_either_signal(self):
        m = self.mod
        orig = self._saved[2]  # setUp stubs display_stalled itself
        saved = (m.vsync_flood_hits, m.xrandr_probe, m.VSYNC_FLOOD_MIN)
        try:
            m.VSYNC_FLOOD_MIN = 150
            m.vsync_flood_hits = lambda: 500
            m.xrandr_probe = lambda: ""
            self.assertEqual(orig()[0], True)
            m.vsync_flood_hits = lambda: 0
            m.xrandr_probe = lambda: "xrandr :0 timed out"
            self.assertEqual(orig()[0], True)
            m.xrandr_probe = lambda: ""
            self.assertEqual(orig()[0], False)
        finally:
            (m.vsync_flood_hits, m.xrandr_probe,
             m.VSYNC_FLOOD_MIN) = saved


class StartTaskPropsTest(unittest.TestCase):
    """The systemd-run argv for container/script carries the props;
    dispatch passes DISPATCH_UNIT_PROPS to devin-dispatch."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved = (m.sh, m.LIMITS_ON, m.enforce_task_limits)
        m.LIMITS_ON = True
        m.TASK_NICE = 10
        m.TASK_CPU_QUOTA = "500%"
        m.TASK_MEM_MAX = "12G"
        self.captured = {}
        m.sh = lambda cmd, **kw: (
            self.captured.update(cmd=cmd, env=kw.get("env")),
            _proc(out="20261010-120000-test\n"))[1]
        m.enforce_task_limits = lambda unit: self.captured.update(
            enforced=unit)

    def tearDown(self):
        (self.mod.sh, self.mod.LIMITS_ON,
         self.mod.enforce_task_limits) = self._saved

    def test_container_argv_has_props(self):
        card = {"id": "c1", "action": {
            "type": "container",
            "container": {"image": "img:1", "cmd": "true"}}}
        unit, tid, err = self.mod.start_task(card, "container")
        argv = self.captured["cmd"]
        self.assertIn("--property=Nice=10", argv)
        self.assertIn("--property=CPUQuota=500%", argv)
        self.assertIn("--property=MemoryMax=12G", argv)
        self.assertEqual(err, "")

    def test_dispatch_passes_unit_props_and_enforces(self):
        card = {"id": "c2", "title": "t", "spec": "do it",
                "action": {"type": "dispatch"}}
        unit, tid, err = self.mod.start_task(card, "dispatch")
        props = self.captured["env"].get("DISPATCH_UNIT_PROPS", "")
        self.assertIn("--property=Nice=10", props)
        self.assertIn("--property=CPUQuota=500%", props)
        self.assertEqual(unit, "devin-task-20261010-120000-test")
        self.assertEqual(self.captured.get("enforced"), unit)


if __name__ == "__main__":
    unittest.main()
