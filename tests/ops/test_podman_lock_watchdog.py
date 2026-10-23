"""podman-lock-watchdog judge/cleanup coverage (card
podman-lock-wedge-watchdog, OPS-0726).

Pins the safety contract from the 2026-10-16 collapse runbook: stale
locks are cleared ONLY on >=3 consecutive dead probes AND zero live
podman/docker CLI procs; a live pause.pid survives; alerts fire once
per episode on both recovery and failure-to-recover. All tests run
offline with injected probe/live/alert fakes.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ops/podman-lock-watchdog.py"

spec = importlib.util.spec_from_file_location("podman_lock_watchdog", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["podman_lock_watchdog"] = mod
spec.loader.exec_module(mod)

FAIL = (False, "rc=124")
OK = (True, "ok")
LIVE = [{"pid": 9, "comm": "podman", "etimes": 3, "args": "podman ps"}]


def run_ticks(n, probes, live=None, alerts=None, clear=None):
    """Drive n ticks with an injected probe sequence."""
    seq = itertools.chain(probes, itertools.repeat(OK))
    sink = alerts if alerts is not None else []
    out = [
        mod.tick(
            probe_fn=lambda t: next(seq),
            live_fn=lambda: list(live or []),
            clear_fn=clear or (lambda dry_run=False:
                               {"removed": ["shm"], "kept": []}),
            renumber_fn=lambda: (True, "rc=0"),
            alert_fn=lambda k, b, d: sink.append(k) or {"ok": 1})
        for _ in range(n)]
    return out


class Tick(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._state = mod.STATE
        mod.STATE = Path(self._td.name) / "state.json"

    def tearDown(self):
        mod.STATE = self._state
        self._td.cleanup()

    def test_below_threshold_no_action(self):
        rs = run_ticks(2, [FAIL, FAIL])
        self.assertEqual(rs[-1]["action"], "none")
        self.assertEqual(rs[-1]["consec_fail"], 2)
        self.assertFalse(rs[-1]["signature"])

    def test_signature_recovers_and_alerts_once(self):
        alerts = []
        rs = run_ticks(3, [FAIL, FAIL, FAIL], alerts=alerts)
        self.assertTrue(rs[2]["signature"])
        self.assertEqual(rs[2]["action"], "recover")
        self.assertEqual(rs[2]["outcome"], "recovered")
        self.assertEqual(alerts, ["recovered"])
        self.assertEqual(mod.load_state()["consec_fail"], 0)

    def test_live_cli_defers(self):
        alerts = []
        rs = run_ticks(3, [FAIL] * 3, live=LIVE, alerts=alerts)
        self.assertEqual(rs[2]["action"], "deferred-live-cli")
        self.assertFalse(rs[2]["signature"])
        self.assertEqual(alerts, [])

    def test_failed_recovery_alerts_critical_then_quiets(self):
        alerts = []
        rs = run_ticks(4, itertools.repeat(FAIL), alerts=alerts)
        self.assertEqual(rs[2]["outcome"], "still-wedged")
        self.assertEqual(alerts, ["failed"])
        # tick 4: inside COOLDOWN_S -> no second rm/renumber attempt
        self.assertEqual(rs[3]["action"], "suppressed-cooldown")
        self.assertEqual(alerts, ["failed"])

    def test_external_recovery_resets_episode(self):
        rs = run_ticks(3, [FAIL, FAIL, OK])
        self.assertEqual(rs[2]["action"], "recovered-external")
        st = mod.load_state()
        self.assertEqual(st["consec_fail"], 0)
        self.assertFalse(st["episode_open"])

    def test_live_pause_pid_kept(self):
        with tempfile.TemporaryDirectory() as td:
            shm, run = Path(td) / "shm", Path(td) / "run"
            (run / "containers" / "c1").mkdir(parents=True)
            (run / "libpod" / "tmp").mkdir(parents=True)
            shm.mkdir()
            (shm / f"libpod_rootless_lock_{mod.UID}").write_text("")
            (run / "containers" / "c1" / "pause.pid").write_text("123")
            (run / "libpod" / "tmp" / "alive.lck").write_text("")
            old = mod.DEV_SHM, mod.RUN_DIR, mod._pid_is_pause
            mod.DEV_SHM, mod.RUN_DIR = str(shm), run
            mod._pid_is_pause = lambda pid: True          # live pause proc
            try:
                out = mod.clear_stale_state()
            finally:
                mod.DEV_SHM, mod.RUN_DIR, mod._pid_is_pause = old
            self.assertEqual(len(out["removed"]), 2)      # shm + alive.lck
            self.assertTrue(any("live pause" in k for k in out["kept"]))
            self.assertTrue((run / "containers" / "c1"
                             / "pause.pid").exists())

    def test_dead_pause_pid_removed(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            (run / "containers" / "c1").mkdir(parents=True)
            (run / "containers" / "c1" / "pause.pid").write_text("99999")
            old = mod.RUN_DIR, mod._pid_is_pause
            mod.RUN_DIR = run
            mod._pid_is_pause = lambda pid: False         # dead
            try:
                out = mod.clear_stale_state()
            finally:
                mod.RUN_DIR, mod._pid_is_pause = old
            self.assertEqual(len(out["removed"]), 1)
            self.assertFalse((run / "containers" / "c1"
                              / "pause.pid").exists())


if __name__ == "__main__":
    unittest.main()
