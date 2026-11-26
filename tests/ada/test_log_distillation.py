"""Unit tests for the log-distillation improvements.

Covers the contracts that protect the digest from lying: suppressed
repeat counts keep their drop window, scan telemetry reaches report/24h,
a truncated baseline never produces 🆕 flags, and one signature on many
hosts is reported once as a fleet incident.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ship = load("log_shipper_under_test", "scripts/ada/log-shipper.py")
report = load("logs_report_under_test", "scripts/ada/logs-report.py")


def raw(ts: str, line: str = "conmon <nwarn>: Failed to write stdin",
        host: str = "idc03", kind: str = "error") -> dict:
    return {"host": host, "journal": "sys", "unit": "init.scope",
            "ts": ts, "kind": kind, "line": line, "cursor": ts,
            "key": f"hostlog/{host}/{ts}"}


def row(ts: str, line: str = "tick error: Remote end closed connection",
        host: str = "idc03", kind: str = "failed", sup: int = 0,
        first: str = "", last: str = "") -> dict:
    return {"host": host, "journal": "sys", "unit": "init.scope",
            "ts": ts, "kind": kind, "line": line, "suppressed": sup,
            "suppressed_first_ts": first, "suppressed_last_ts": last}


class RepeatCap(unittest.TestCase):
    def test_suppressed_count_and_window_land_on_marker(self):
        n = ship.REPEAT_CAP + 2
        rows = [raw(f"2026-11-26T01:{i:02d}:00+00:00") for i in range(n)]
        kept, sup = ship._cap_repeats(rows)
        self.assertEqual(len(kept), ship.REPEAT_CAP)
        self.assertEqual(sup, 2)
        marker = kept[-1]
        self.assertEqual(marker["suppressed"], 2)
        self.assertEqual(marker["suppressed_first_ts"],
                         "2026-11-26T01:25:00+00:00")
        self.assertEqual(marker["suppressed_last_ts"],
                         "2026-11-26T01:26:00+00:00")

    def test_doc_exposes_window_meta(self):
        r = raw("2026-11-26T01:00:00+00:00")
        r.update({"suppressed": 3,
                  "suppressed_first_ts": "2026-11-26T01:25:00+00:00",
                  "suppressed_last_ts": "2026-11-26T01:27:00+00:00"})
        meta = ship._doc(r)["meta"]
        self.assertEqual(meta["suppressed"], ["3"])
        self.assertEqual(meta["suppressed_first_ts"],
                         ["2026-11-26T01:25:00+00:00"])
        self.assertEqual(meta["suppressed_last_ts"],
                         ["2026-11-26T01:27:00+00:00"])


class StateDoc(unittest.TestCase):
    def test_scan_stats_are_published(self):
        stats = {"truncated": True, "scanned": 50000, "pages": 10,
                 "last_page": 1000, "elapsed_s": 41.0, "max_docs": 250000}
        now = "2026-11-26T02:00:00+00:00"
        content = report.report_payload(
            [{"host": "idc03", "total": 7, "severe": 2}], 24, stats,
            now=__import__("datetime").datetime.fromisoformat(now))
        body = __import__("json").loads(content["contentMd"])
        self.assertEqual(body["scan"], stats)
        self.assertEqual(body["hosts"]["idc03"], {"total": 7, "severe": 2})
        self.assertEqual(content["key"], "report/24h")


class Distillation(unittest.TestCase):
    def test_truncated_baseline_suppresses_new_flags(self):
        rows = [row(f"2026-11-26T01:{i:02d}:00+00:00") for i in range(4)]
        # one normalized signature across the four rows
        self.assertEqual(report.distill(rows, set())[0]["new"], 1)
        self.assertEqual(report.distill(rows, None)[0]["new"], 0)

    def test_fleet_rollup_groups_cross_host_repeats(self):
        rows = [
            row("2026-11-26T01:00:00+00:00", host="idc03", sup=9),
            row("2026-11-26T01:01:00+00:00", host="con01", sup=4),
            row("2026-11-26T01:02:00+00:00", host="mn01",
                line="a different one-off"),
        ]
        fleet = report.fleet_rollup(rows)
        self.assertEqual(len(fleet), 1)
        self.assertEqual(fleet[0]["n"], 15)
        self.assertEqual(fleet[0]["hosts"], ["con01", "idc03"])

    def test_block_shows_window_and_truncation(self):
        summary = report.distill([
            row("2026-11-26T01:00:00+00:00", sup=3,
                first="2026-11-26T01:25:00+00:00",
                last="2026-11-26T01:27:00+00:00")], None)
        block = report.logs_block(
            summary, "24h", stats={"scanned": 10, "elapsed_s": 41.0,
                                   "truncated": True})
        self.assertIn("TRUNCATED", block)
        self.assertIn("suppressed drops 2026-11-26T01:25..01:27", block)


if __name__ == "__main__":
    unittest.main()
