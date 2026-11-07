"""job-dispatcher failure-isolation coverage (card
fix-chaba-jobs-network-scan-failure-isolation).

Pins the policy added 2026-10-27: dispatcher jobs are noncritical by
default — a failing job is isolated (other due jobs still run), backs off
exponentially (interval * factor**(n-1), floored at interval, capped),
persists last_success/last_failure/failure_count/next_retry, alerts once
per failure episode via board-api /inbox (local focus-inbox fallback,
self-heals on recovery), and only `critical: true` jobs fail the service
tick. All tests run offline with injected run/alert/post fakes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from functools import partial
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/job-dispatcher.py"

spec = importlib.util.spec_from_file_location("job_dispatcher", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["job_dispatcher"] = mod
spec.loader.exec_module(mod)

HOST = "testbox"


def job(jid, every=60, critical=None, **kw):
    j = {"id": jid, "name": jid, "host": HOST,
         "dispatch": "dispatcher", "every": every,
         "exec": "/bin/true", "timeout": "30s"}
    if critical is not None:
        j["critical"] = critical
    j.update(kw)
    return j


def manifest(jobs, **policy):
    return {"config": {"failure_policy": policy}, "jobs": jobs}


class Tick(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        d = Path(self._td.name)
        self.state = d / "state.json"
        self.results = d / "timeline.jsonl"
        self.inbox = d / "focus-inbox"
        self.lines = []

    def tearDown(self):
        self._td.cleanup()

    def tick(self, man, now, run_fn, alert_fn=None, dry_run=False):
        return mod.tick(man, HOST, self.state, self.results, now=now,
                        dry_run=dry_run, run_fn=run_fn, alert_fn=alert_fn,
                        inbox_dir=self.inbox, out=self.lines.append)

    def read_state(self):
        return json.loads(self.state.read_text())

    def read_results(self):
        return [json.loads(l) for l in self.results.read_text().splitlines()]

    # -- failure isolation --------------------------------------------------

    def test_failing_job_does_not_block_others(self):
        calls = []
        def run(j, cmd, timeout):
            calls.append(j["id"])
            return (False, 1, "boom") if j["id"] == "bad" else (True, 0, "")
        res = self.tick(manifest([job("bad"), job("good")]), 1000, run)
        self.assertEqual(calls, ["bad", "good"])   # both attempted, in order
        self.assertEqual(res["failed"], ["bad"])
        self.assertEqual(res["failed_critical"], [])
        st = self.read_state()
        self.assertTrue(st["good"]["ok"])
        self.assertFalse(st["bad"]["ok"])
        recs = self.read_results()
        self.assertEqual([r["name"] for r in recs], ["bad", "good"])

    def test_dispatcher_exception_isolated_to_job(self):
        calls = []
        def run(j, cmd, timeout):
            calls.append(j["id"])
            if j["id"] == "crash":
                raise OSError("cwd gone")
            return True, 0, ""
        res = self.tick(manifest([job("crash"), job("good")]), 1000, run)
        self.assertEqual(calls, ["crash", "good"])
        self.assertEqual(res["failed"], ["crash"])
        st = self.read_state()
        self.assertEqual(st["crash"]["exit_code"], mod.EXEC_ERR)
        self.assertTrue(st["good"]["ok"])

    # -- backoff ------------------------------------------------------------

    def test_failure_backs_off_then_retries(self):
        always_fail = lambda j, cmd, timeout: (False, 1, "x")
        man = manifest([job("j", every=60)], backoff_cap="10min")
        self.tick(man, 1000, always_fail)
        st = self.read_state()["j"]
        self.assertEqual(st["failure_count"], 1)
        # first failure retries on the normal cadence (interval floor)
        self.assertEqual(st["next_retry"], st["last_run"] + 60)

        res = self.tick(man, 1030, always_fail)
        self.assertEqual(res["ran"], [])               # not due yet at all

        res = self.tick(man, 1061, always_fail)        # past next_retry
        self.assertEqual(res["ran"], ["j"])
        st = self.read_state()["j"]
        self.assertEqual(st["failure_count"], 2)
        # second failure doubles: 60 * 2 = 120s
        self.assertEqual(st["next_retry"], st["last_run"] + 120)

        res = self.tick(man, 1130, always_fail)        # due by interval,
        self.assertEqual(res["ran"], [])               # still inside backoff
        self.assertEqual(res["backoff"], ["j"])

    def test_backoff_cap_and_interval_floor(self):
        # cap wins once the exponential term exceeds it
        self.assertEqual(mod.backoff_delay(60, 10, 2, 300), 300)
        # but never retries faster than the job's own cadence
        self.assertEqual(mod.backoff_delay(86400, 3, 2, 300), 86400)
        self.assertEqual(mod.backoff_delay(60, 1, 2, 300), 60)
        self.assertEqual(mod.backoff_delay(60, 2, 2, 300), 120)

    def test_backoff_resets_after_success(self):
        seq = iter([(False, 1, "x"), (False, 1, "x"), (True, 0, "")])
        run = lambda j, cmd, timeout: next(seq)
        man = manifest([job("j", every=60)])
        self.tick(man, 1000, run)
        self.tick(man, 1100, run)          # past next_retry, fails again
        st = self.read_state()["j"]
        self.assertEqual(st["failure_count"], 2)
        self.tick(man, 1300, run)          # recovery
        st = self.read_state()["j"]
        self.assertEqual(st["failure_count"], 0)
        self.assertEqual(st["next_retry"], 0)
        self.assertFalse(st["alerted"])
        self.assertTrue(st["ok"])
        self.assertIn("last_success", st)

    # -- state persistence --------------------------------------------------

    def test_state_persists_across_ticks(self):
        fail = lambda j, cmd, timeout: (False, 7, "dead")
        ok = lambda j, cmd, timeout: (True, 0, "")
        man = manifest([job("a", every=60), job("b", every=60)])
        self.tick(man, 1000, lambda j, c, t: fail(j, c, t)
                  if j["id"] == "a" else ok(j, c, t))
        st = self.read_state()
        for k in ("last_run", "last_failure", "failure_count", "next_retry"):
            self.assertIn(k, st["a"])
        self.assertIn("last_success", st["b"])
        self.assertNotIn("last_failure", st["b"])
        # a is backed off, b simply not due — a second tick persists both
        res = self.tick(man, 1030, ok)
        self.assertEqual(res["ran"], [])
        st2 = self.read_state()
        self.assertEqual(st2["a"]["failure_count"], 1)
        self.assertTrue(st2["b"]["ok"])

    def test_results_record_carries_backoff_evidence(self):
        fail = lambda j, cmd, timeout: (False, 2, "nope")
        self.tick(manifest([job("a", every=60)]), 1000, fail)
        rec = self.read_results()[0]
        for k in ("ts", "name", "command", "ok", "exit_code",
                  "duration_ms", "host", "critical", "failure_count",
                  "backoff_s", "err"):
            self.assertIn(k, rec)
        self.assertEqual(rec["failure_count"], 1)
        self.assertEqual(rec["backoff_s"], 60)
        self.assertEqual(rec["err"], "nope")

    # -- service exit policy --------------------------------------------------

    def test_noncritical_failure_does_not_fail_tick(self):
        fail = lambda j, cmd, timeout: (False, 1, "x")
        res = self.tick(manifest([job("a")]), 1000, fail)
        self.assertEqual(res["failed_critical"], [])   # -> main() exit 0

    def test_critical_failure_fails_tick(self):
        def run(j, cmd, timeout):
            return (False, 1, "x") if j["id"] == "crit" else (True, 0, "")
        res = self.tick(manifest(
            [job("crit", critical=True), job("soft")]), 1000, run)
        self.assertEqual(res["failed_critical"], ["crit"])  # -> exit 1
        self.assertEqual(res["failed"], ["crit"])

    # -- alerts ---------------------------------------------------------------

    def test_alert_once_per_episode_and_recovers(self):
        alerts = []
        alert = lambda j, host, rec, st, inbox: alerts.append(j["id"]) or True
        seq = iter([(False, 1, "x"), (False, 1, "x"), (True, 0, ""),
                    (False, 1, "x")])
        run = lambda j, cmd, timeout: next(seq)
        man = manifest([job("a", every=60)])
        self.tick(man, 1000, run, alert)   # fail -> alert
        self.tick(man, 1100, run, alert)   # fail again -> still suppressed
        self.assertEqual(alerts, ["a"])
        self.tick(man, 1300, run, alert)   # recover -> resets flag
        self.tick(man, 1400, run, alert)   # new episode -> alerts again
        self.assertEqual(alerts, ["a", "a"])

    def test_default_alert_falls_back_to_inbox_file(self):
        """/inbox unreachable -> local focus-inbox file; recovery clears it."""
        def dead_post(*a, **kw):
            raise OSError("board-api down")
        alert = partial(mod.default_alert, post_fn=dead_post)
        fail = lambda j, cmd, timeout: (False, 1, "x")
        ok = lambda j, cmd, timeout: (True, 0, "")
        man = manifest([job("a", every=60)])
        self.tick(man, 1000, fail, alert)
        f = self.inbox / f"job-fail-{HOST}-a.yml"
        self.assertTrue(f.exists())
        self.assertIn("job-fail: a", f.read_text())
        self.tick(man, 1100, ok, alert)    # recovery self-heals the file
        self.assertFalse(f.exists())

    # -- dry run --------------------------------------------------------------

    def test_dry_run_writes_nothing(self):
        run = lambda j, cmd, timeout: (_ for _ in ()).throw(
            AssertionError("dry-run must not exec"))
        self.tick(manifest([job("a", every=60)]), 1000, run, dry_run=True)
        # dry_run path: state not created, results not written
        self.assertFalse(self.state.exists())
        self.assertFalse(self.results.exists())
        self.assertTrue(any("due a" in l for l in self.lines))


if __name__ == "__main__":
    unittest.main()
