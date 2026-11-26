"""Tests for scripts/ops/job-health-sweep.py — journal streak counting,
manifest enumeration, timer-state probes, undeclared-unit drift, and
the board-api state-change (anti-noise) lifecycle."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ops" / "job-health-sweep.py"

spec = importlib.util.spec_from_file_location("job_health_sweep", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["job_health_sweep"] = mod
spec.loader.exec_module(mod)

UNIT = "demo.service"


def ev(ts: int, msg: str):
    return (ts, msg)


def fail_activation(ts: int, result: str = "exit-code",
                    out: str = "") -> list:
    """One failed oneshot activation, oldest->newest journal order:
    Starting -> unit stdout -> 'Failed with result' -> 'Failed to start'."""
    return [
        ev(ts, f"Starting {UNIT}.service - demo (job:demo)"),
        *([ev(ts + 1, out)] if out else []),
        ev(ts + 2, f"{UNIT}: Failed with result '{result}'."),
        ev(ts + 3, f"Failed to start {UNIT}.service - demo (job:demo)."),
    ]


def ok_activation(ts: int) -> list:
    return [
        ev(ts, f"Starting {UNIT}.service - demo (job:demo)"),
        ev(ts + 1, f"Finished {UNIT}.service - demo (job:demo)."),
        ev(ts + 2, f"{UNIT}: Deactivated successfully."),
    ]


class AnalyzeUnit(unittest.TestCase):
    def test_consecutive_failures_counted_once_per_activation(self):
        # 'Failed with result' + 'Failed to start' are two journal lines
        # for ONE failed activation — the streak must not double-count.
        events = fail_activation(100) + fail_activation(200) \
            + fail_activation(300)
        a = mod.analyze_unit(UNIT, events)
        self.assertEqual(a["consec"], 3)
        self.assertEqual(a["fails"], 3)
        self.assertEqual(a["attempts"], 3)
        self.assertEqual(a["successes"], 0)

    def test_success_breaks_streak(self):
        events = (fail_activation(100) + fail_activation(200)
                  + ok_activation(300) + fail_activation(400)
                  + fail_activation(500))
        a = mod.analyze_unit(UNIT, events)
        self.assertEqual(a["consec"], 2)
        self.assertEqual(a["fails"], 4)
        self.assertEqual(a["successes"], 1)

    def test_finished_marker_ends_walk(self):
        # anything older than the last success is irrelevant to consec
        events = (fail_activation(100) + fail_activation(200)
                  + fail_activation(300) + ok_activation(400)
                  + fail_activation(500))
        a = mod.analyze_unit(UNIT, events)
        self.assertEqual(a["consec"], 1)

    def test_deactivated_success_counts_as_ok(self):
        events = [
            ev(100, f"Starting {UNIT}.service"),
            ev(101, f"{UNIT}: Deactivated successfully."),
        ]
        a = mod.analyze_unit(UNIT, events)
        self.assertEqual(a["consec"], 0)
        self.assertEqual(a["successes"], 1)

    def test_orphan_failed_with_result_counts(self):
        # a 'Failed with result' with no paired 'Failed to start'
        # (cancelled/aborted activation) still counts as a failure
        events = [ev(100, f"{UNIT}: Failed with result 'timeout'.")]
        a = mod.analyze_unit(UNIT, events)
        self.assertEqual(a["consec"], 1)

    def test_fwr_older_than_fts_is_one_activation(self):
        # normal pair order: FwR chronologically precedes FtS — the
        # dedupe must not count it twice (covered above too, asserted
        # explicitly here for the pair-only case)
        events = [
            ev(100, f"{UNIT}: Failed with result 'exit-code'."),
            ev(101, f"Failed to start {UNIT}.service"),
        ]
        a = mod.analyze_unit(UNIT, events)
        self.assertEqual(a["consec"], 1)

    def test_last_error_prefers_errorish_output(self):
        events = fail_activation(
            100, out="Error: connection refused by upstream")
        a = mod.analyze_unit(UNIT, events)
        self.assertIn("connection refused", a["last_error"])

    def test_last_error_falls_back_to_result_reason(self):
        events = fail_activation(100, result="timeout")
        a = mod.analyze_unit(UNIT, events)
        self.assertIn("timeout", a["last_error"])

    def test_empty_journal(self):
        a = mod.analyze_unit(UNIT, [])
        self.assertEqual(a["consec"], 0)
        self.assertEqual(a["attempts"], 0)
        self.assertEqual(a["entries"], 0)


class LoadJobs(unittest.TestCase):
    def _manifest(self, tmp: Path) -> Path:
        p = tmp / "ssot.jobs.yml"
        p.write_text(
            "jobs:\n"
            "- id: alpha\n  host: idc02\n  dispatch: systemd\n"
            "- id: beta\n  host: idc02\n  dispatch: systemd\n"
            "  enabled: false\n"
            "- id: gamma\n  host: idc03\n  dispatch: systemd\n"
            "- id: delta\n  host: idc02\n  dispatch: dispatcher\n"
            "  every: 5min\n"
            "- id: eps\n  host: idc02\n  dispatch: systemd\n"
            "  enabled: true\n")
        return p

    def test_filters_host_dispatch_enabled(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = mod.load_jobs(self._manifest(Path(td)), "idc02")
        self.assertEqual([j["id"] for j in jobs], ["alpha", "eps"])

    def test_other_host_empty(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = mod.load_jobs(self._manifest(Path(td)), "mn01")
        self.assertEqual(jobs, [])


class TimerProblems(unittest.TestCase):
    def test_missing_units_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(mod, "UNIT_DIR", Path(td)):
                probs, _ = mod.timer_problems("ghost-job")
        self.assertTrue(any(p.startswith("units-missing") for p in probs))

    def test_disabled_inactive_timer_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "demo.service").write_text("[Service]\n")
            (d / "demo.timer").write_text("[Timer]\n")

            def fake_ctl(*args):
                if args[0] == "is-enabled":
                    return 1, "disabled"
                if args[0] == "is-active":
                    return 3, "inactive"
                return 0, ""

            with patch.object(mod, "UNIT_DIR", d), \
                    patch.object(mod, "systemctl_user", fake_ctl):
                probs, info = mod.timer_problems("demo")
        self.assertIn("timer-not-enabled:disabled", probs)
        self.assertIn("timer-inactive:inactive", probs)

    def test_healthy_timer_clean(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "demo.service").write_text("[Service]\n")
            (d / "demo.timer").write_text("[Timer]\n")

            def fake_ctl(*args):
                return 0, "enabled" if args[0] == "is-enabled" \
                    else "active"

            with patch.object(mod, "UNIT_DIR", d), \
                    patch.object(mod, "systemctl_user", fake_ctl):
                probs, _ = mod.timer_problems("demo")
        self.assertEqual(probs, [])


class UndeclaredUnits(unittest.TestCase):
    def test_only_tagged_undeclared_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "mine.service").write_text(
                "[Unit]\nDescription=x (job:mine, rendered)\n")
            (d / "theirs.service").write_text(
                "[Unit]\nDescription=y (job:theirs, rendered)\n")
            (d / "hand.service").write_text(
                "[Unit]\nDescription=hand installed, no tag\n")
            (d / "mine.timer").write_text("[Timer]\n")
            with patch.object(mod, "UNIT_DIR", d):
                found = mod.undeclared_units({"mine"})
        self.assertEqual(found, {"theirs": ["theirs.service"]})


class EvaluateThresholds(unittest.TestCase):
    def _job(self, jid="demo"):
        return {"id": jid, "name": jid}

    def test_consec_three_flags(self):
        events = fail_activation(1) + fail_activation(2) \
            + fail_activation(3)
        with patch.object(mod, "timer_problems",
                          lambda jid: ([], {})), \
                patch.object(mod, "journal_events",
                             lambda u, s: (events, "")):
            verdicts, errs = mod.evaluate([self._job()], "30 days ago")
        self.assertEqual(errs, [])
        v = verdicts["demo"]
        self.assertIn("consecutive-failures:3", v["reasons"])

    def test_single_attempt_zero_success_flags(self):
        events = fail_activation(1)
        with patch.object(mod, "timer_problems",
                          lambda jid: ([], {})), \
                patch.object(mod, "journal_events",
                             lambda u, s: (events, "")):
            verdicts, _ = mod.evaluate([self._job()], "30 days ago")
        v = verdicts["demo"]
        self.assertTrue(any(r.startswith("zero-successes")
                            for r in v["reasons"]))

    def test_two_consec_below_threshold_green(self):
        events = fail_activation(1) + fail_activation(2) \
            + ok_activation(3)
        with patch.object(mod, "timer_problems",
                          lambda jid: ([], {})), \
                patch.object(mod, "journal_events",
                             lambda u, s: (events, "")):
            verdicts, _ = mod.evaluate([self._job()], "30 days ago")
        self.assertEqual(verdicts["demo"]["reasons"], [])

    def test_timer_problem_surfaces_without_journal(self):
        with patch.object(mod, "timer_problems",
                          lambda jid: (["timer-inactive:inactive"], {})), \
                patch.object(mod, "journal_events",
                             lambda u, s: ([], "")):
            verdicts, _ = mod.evaluate([self._job()], "30 days ago")
        self.assertIn("timer-inactive:inactive",
                      verdicts["demo"]["reasons"])


class RunSweepBoardLifecycle(unittest.TestCase):
    """Anti-noise contract: card created once, comments only on state
    change, auto-close when green."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_state = mod.STATE
        mod.STATE = Path(self.tmp.name) / "sweep-state.json"
        self.calls = []

    def tearDown(self):
        mod.STATE = self._old_state
        self.tmp.cleanup()

    def _fake_board(self, exists="missing"):
        def fake_post(path, body):
            self.calls.append((path, dict(body)))
            return True, "ok"

        def fake_exists(cid):
            return exists, ""

        return patch.object(mod, "post", fake_post), \
            patch.object(mod, "card_exists", fake_exists)

    def _verdict(self, failing=True):
        return {"id": "demo", "name": "demo",
                "reasons": ["consecutive-failures:3"] if failing else [],
                "unit": "demo.service", "consec": 3 if failing else 0,
                "fails": 3, "successes": 0, "attempts": 3,
                "entries": 9, "oldest_ts": 0, "last_fail_ts": 0,
                "last_error": "boom"}

    def _run(self, verdicts, exists="missing"):
        p1, p2 = self._fake_board(exists)
        with patch.object(mod, "evaluate",
                          lambda j, s, workers=8: (verdicts, [])), \
                patch.object(mod, "undeclared_units", lambda d: {}), \
                p1, p2:
            return mod.run_sweep("idc02", [{"id": "demo", "name": "demo"}],
                                 "30 days ago")

    def test_first_failure_creates_card_and_comments(self):
        self._run({"demo": self._verdict(True)})
        paths = [c[0] for c in self.calls]
        self.assertIn("/card", paths)
        self.assertEqual(paths.count("/comment"), 1)
        card = next(b for p, b in self.calls if p == "/card")
        self.assertEqual(card["id"], "job-auto-health-idc02")
        self.assertEqual(card["column"], "review")

    def test_second_run_same_failure_is_silent(self):
        v = {"demo": self._verdict(True)}
        self._run(v)
        self.calls.clear()
        # card now exists open; same verdict -> no new comments
        self._run(v, exists="open")
        self.assertEqual([c[0] for c in self.calls], [])

    def test_recovery_comments_then_closes(self):
        self._run({"demo": self._verdict(True)})
        self.calls.clear()
        self._run({"demo": self._verdict(False)}, exists="open")
        paths = [c[0] for c in self.calls]
        self.assertEqual(paths.count("/comment"), 1)
        self.assertIn("/action", paths)
        action = next(b for p, b in self.calls if p == "/action")
        self.assertEqual(action["do"], "close")

    def test_healthy_host_never_creates_card(self):
        self._run({"demo": self._verdict(False)}, exists="missing")
        self.assertEqual(self.calls, [])

    def test_relapse_after_recovery_alerts_again(self):
        # fail -> recover -> fail again: the relapse is a NEW episode
        # and must comment (request_id episode counter differs).
        self._run({"demo": self._verdict(True)})
        self.calls.clear()
        self._run({"demo": self._verdict(False)}, exists="open")
        self.calls.clear()
        # card closed -> done; failing again reopens + comments
        self._run({"demo": self._verdict(True)}, exists="done")
        paths = [c[0] for c in self.calls]
        self.assertIn("/action", paths)   # reopen move->review
        self.assertIn("/comment", paths)  # new-failure comment


if __name__ == "__main__":
    unittest.main()
