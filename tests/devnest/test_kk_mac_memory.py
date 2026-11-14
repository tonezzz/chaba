import time
import unittest
from unittest.mock import patch

from scripts.devnest import kk_mac_memory as km


class _R:
    def __init__(self, out="", rc=0):
        self.stdout = out.encode()
        self.returncode = rc


def _ssh_seq(outputs):
    it = iter(outputs)

    def run(cmd, timeout=None, **kw):
        return next(it)
    return run


class SampleTests(unittest.TestCase):
    def test_memory_pressure_parse(self):
        out = ("The system has 68719476736 bytes of memory.\n"
               "System-wide memory free percentage: 72%\n")
        s = km.sample(ssh_run=lambda *a, **k: _R(out))
        self.assertTrue(s["ok"])
        self.assertEqual(s["free_pct"], 72.0)

    def test_vm_stat_fallback(self):
        def run(cmd, timeout=None, **kw):
            if "memory_pressure" in " ".join(cmd):
                return _R("")  # `|| true` keeps rc=0 with empty output
            return _R("Pages free: 100.\nPages inactive: 300.\n"
                      "Pages active: 400.\n")
        s = km.sample(ssh_run=run)
        self.assertTrue(s["ok"])
        self.assertAlmostEqual(s["free_pct"], 50.0, places=1)

    def test_unparseable_fails(self):
        s = km.sample(ssh_run=lambda *a, **k: _R("garbage"))
        self.assertFalse(s["ok"])
        self.assertIsNone(s["free_pct"])


class EvaluateTests(unittest.TestCase):
    def _snap(self, pct, ok=True):
        return {"ok": ok, "free_pct": pct, "level": None}

    def test_preload_floor(self):
        self.assertTrue(km.evaluate(self._snap(59.9), phase="pre"))
        self.assertFalse(km.evaluate(self._snap(60.0), phase="pre"))
        # 55% is fine post-preload as long as above abort floor
        self.assertFalse(km.evaluate(self._snap(55.0), phase="during"))

    def test_abort_floor_any_phase(self):
        self.assertTrue(km.evaluate(self._snap(49.9), phase="during"))
        self.assertTrue(km.evaluate(self._snap(49.9), phase="post"))
        self.assertTrue(km.evaluate(self._snap(49.9), phase="pre"))

    def test_sample_failure_only_blocks_pre(self):
        bad = {"ok": False, "free_pct": None}
        self.assertIn("memory_sample_failed",
                      km.evaluate(bad, phase="pre"))
        self.assertEqual(km.evaluate(bad, phase="during"), [])


class MonitorLifecycleTests(unittest.TestCase):
    """The real MemoryMonitor must start and stop without raising — a
    threading.Event named _stop shadowed Thread._stop() and broke join()
    (found by the 2026-11-14 lane soak)."""

    def test_start_stop_join_clean(self):
        mon = km.MemoryMonitor("kk-mac", interval=0.01,
                               ssh_run=lambda *a, **k: _R(
                                   out="free percentage: 70%"))
        mon.start()
        time.sleep(0.05)
        mon.stop()  # must not raise
        self.assertFalse(mon.is_alive())
        self.assertTrue(mon.samples)


if __name__ == "__main__":
    unittest.main()
