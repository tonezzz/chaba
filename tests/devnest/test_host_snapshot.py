"""Unit tests for scripts/devnest/host_snapshot.py (AUD-1033) — the
single-call read-only host probe that replaces the ~10-command
micro-probe storm in the ops-readonly lane. Parsers are exercised on
fixtures; collect() is checked for contract shape and independent
degradation — no real systemctl required.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "host_snapshot", REPO / "scripts" / "devnest" / "host_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MEMINFO = """MemTotal:       16384000 kB
MemFree:          512000 kB
MemAvailable:    3000000 kB
Buffers:          100000 kB
"""

LOADAVG = "1.25 0.75 0.50 2/345 6789\n"
UPTIME = "2666013.37 5339000.00\n"

FAILED_SYSTEM = "ssot-optimization-snapshot.service loaded failed failed snap\nchaba-audit-full.service   loaded failed failed audit\n"
FAILED_USER = "devin-bank-distill.service loaded failed failed distill\n"


class ParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_loadavg(self):
        with patch.object(self.m, "_read", return_value=LOADAVG):
            self.assertEqual(self.m.loadavg(), (1.25, 0.75, 0.50))

    def test_uptime(self):
        with patch.object(self.m, "_read", return_value=UPTIME):
            self.assertAlmostEqual(self.m.uptime_seconds(), 2666013.37)

    def test_mem_mb_prefers_available(self):
        with patch.object(self.m, "_read", return_value=MEMINFO):
            total, avail = self.m.mem_mb()
        self.assertEqual(total, 16000)
        self.assertEqual(avail, 2929)

    def test_mem_mb_falls_back_to_free(self):
        no_avail = MEMINFO.replace("MemAvailable:    3000000 kB\n", "")
        with patch.object(self.m, "_read", return_value=no_avail):
            total, avail = self.m.mem_mb()
        self.assertEqual(avail, 500)

    def test_failed_units_parse(self):
        calls = []

        def fake_run(cmd, timeout):
            calls.append(cmd)
            return FAILED_SYSTEM if "--user" not in cmd else FAILED_USER

        with patch.object(self.m, "_run", side_effect=fake_run):
            sys_units = self.m.failed_units(False, 5)
            usr_units = self.m.failed_units(True, 5)
        self.assertEqual(sys_units, ["ssot-optimization-snapshot.service",
                                   "chaba-audit-full.service"])
        self.assertEqual(usr_units, ["devin-bank-distill.service"])
        self.assertIn("--no-legend", calls[0])
        self.assertEqual(calls[1][:2], ["systemctl", "--user"])


class CollectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_contract_shape(self):
        """The emitted keys are exactly the ops-readonly lane contract
        (fixture/task.yaml #contract.required_fields) plus errors."""
        with patch.object(self.m, "failed_units",
                          side_effect=lambda user, t: ["u.service"] if not user else []):
            snap = self.m.collect()
        for k in ("host", "collected_at", "uptime_seconds", "load1",
                  "load5", "load15", "cpu_count", "mem_total_mb",
                  "mem_available_mb", "disk_root_pct", "failed_units",
                  "read_only"):
            self.assertIn(k, snap, k)
        self.assertTrue(snap["read_only"])
        self.assertIsInstance(snap["failed_units"], list)
        self.assertNotIn("errors", snap)

    def test_probe_failure_degrades_not_aborts(self):
        with patch.object(self.m, "failed_units",
                          side_effect=RuntimeError("no systemctl")), \
             patch.object(self.m, "mem_mb",
                          side_effect=FileNotFoundError("no meminfo")):
            snap = self.m.collect()
        self.assertEqual(snap["failed_units"], [])
        self.assertEqual(snap["mem_total_mb"], -1)
        self.assertIn("errors", snap)
        self.assertTrue(any("failed_user" in e or "failed_system" in e
                            for e in snap["errors"]))
        self.assertTrue(any("mem_mb" in e for e in snap["errors"]))
        # independent probes still landed
        self.assertGreater(snap["cpu_count"], 0)
        self.assertTrue(snap["read_only"])

    def test_main_emits_json(self):
        import io, sys
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            with patch.object(sys, "argv", ["host_snapshot.py"]):
                self.assertEqual(self.m.main(), 0)
        finally:
            sys.stdout = old
        snap = json.loads(buf.getvalue())
        self.assertTrue(snap["read_only"])


if __name__ == "__main__":
    unittest.main()
