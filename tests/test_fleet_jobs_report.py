import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "fleet_jobs_report", REPO / "scripts" / "fleet-jobs-report.py")
report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = report
spec.loader.exec_module(report)


class TestClaimStats(unittest.TestCase):
    def test_counts_running_by_host_and_lane(self):
        stats = report.collect_claim_stats([
            {"action": {"status": "running", "runner": "idc02",
                        "lane": "paid_frontier"}},
            {"action": {"status": "queued", "host": "tony-omen"}},
            {"action": {"status": "failed", "runner": "idc02"}},
            {"action": {"status": "done", "runner": "mn01"}},
            {"action": {"status": "idle", "runner": "tony-dell"}},
        ])

        self.assertEqual(stats["running"], 1)
        self.assertEqual(stats["queued"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["by_host"]["idc02"]["running"], 1)
        self.assertEqual(stats["by_host"]["tony-omen"]["queued"], 1)
        self.assertEqual(stats["by_lane"]["paid_frontier"]["running"], 1)

    def test_legacy_doing_is_reported_as_running(self):
        stats = report.collect_claim_stats([
            {"action": {"status": "doing", "runner": "idc03"}},
        ])
        self.assertEqual(stats["running"], 1)
        self.assertEqual(stats["by_host"]["idc03"]["running"], 1)


class TestReportRendering(unittest.TestCase):
    def test_host_sections_use_host_specific_counts(self):
        claims = report.collect_claim_stats([
            {"action": {"status": "running", "runner": "idc02",
                        "lane": "paid_frontier"}},
            {"action": {"status": "failed", "runner": "tony-omen"}},
        ])
        savings = {
            "lanes": {"free-opencode": {
                "completed": 1, "verified": 1, "tokens_total": 30505,
            }},
            "pack_tokens": 137377,
            "pack_cost_usd": 0,
            "unevidenced_lane_uses": [],
        }
        text = report.render_report(
            "20261117", {}, {}, claims, [],
            {"idc02": [], "tony-omen": []}, savings, {})

        idc02 = text.split("## Host: idc02", 1)[1].split("## Host:", 1)[0]
        omen = text.split("## Host: tony-omen", 1)[1]
        self.assertIn("- Running: 1", idc02)
        self.assertIn("- Failed: 0", idc02)
        self.assertIn("- Running: 0", omen)
        self.assertIn("- Failed: 1", omen)
        self.assertIn("| paid_frontier | 0 | 0 | 1 | 0 | 0 |", text)
        self.assertIn("| free-opencode | 1 | 1 | 30505 |", text)
        self.assertIn("not an avoided-cost estimate", text)


class TestTimerRollup(unittest.TestCase):
    ROLLUP_MD = """# Timer Timeline — fleet

**4 timers** · 🟢 2 · 🟡 0 · 🔴 1 · ⬛ 1

| timer | host | last run | result | state |
|---|---|---|---|---|

| `chaba-repo-sync` | tony-dell | 11-21 16:22 | success (exit 0) | 🟢 ok |
| `cms-h3-publish` | tony-dell | 11-21 16:23 | exit-code (exit 1) | 🔴 FAILING |
| `kanban-commit` | idc03 | 11-21 16:30 | success (exit 0) | 🟢 ok |
| `ada-standby` | mn01 | - | success (exit 0) | ⬛ off |
| `idc01` | — | — | — | — | ⚠️ unreachable (ssh timed out) | — |

## ⚠️ Attention

| `cms-h3-publish` | tony-dell | 11-21 16:23 | exit-code (exit 1) | 🔴 FAILING |
| `idc01` | — | — | — | — | ⚠️ unreachable (ssh timed out) | — |
"""

    def _parse(self):
        with patch.object(report, "_post_json",
                          return_value={"contentMd": self.ROLLUP_MD,
                                        "meta": {"updated": ["u1"]}}):
            return report.read_timer_rollup()

    def test_parses_states_per_host(self):
        rollup = self._parse()
        dell = rollup["hosts"]["tony-dell"]
        self.assertEqual(dell["counts"]["ok"], 1)
        self.assertEqual(dell["counts"]["failing"], 1)
        self.assertEqual(
            dell["timers"]["cms-h3-publish"]["state"], "failing")
        self.assertEqual(rollup["hosts"]["mn01"]["counts"]["off"], 1)
        self.assertEqual(rollup["counts"]["failing"], 1)
        self.assertEqual(rollup["total"], 4)
        self.assertEqual(rollup["updated"], "u1")

    def test_unreachable_row_becomes_host_not_timer(self):
        rollup = self._parse()
        self.assertTrue(rollup["hosts"]["idc01"]["unreachable"])
        self.assertNotIn("idc01", rollup["hosts"].get("—", {}))
        self.assertNotIn("—", rollup["hosts"])

    def test_attention_rows_not_double_counted(self):
        rollup = self._parse()
        # cms-h3-publish appears twice in the doc (table + Attention)
        self.assertEqual(rollup["counts"]["failing"], 1)
        self.assertEqual(rollup["total"], 4)


class TestHostNorm(unittest.TestCase):
    def test_generated_host_ids_normalize(self):
        self.assertEqual(report.norm_host("tony_dell"), "tony-dell")
        self.assertEqual(report.norm_host("idc03"), "idc03")


class TestCmsPublication(unittest.TestCase):
    def test_uses_report_write_door_and_stable_slug(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b'{"slug":"fleet-jobs-report"}'

        with patch.object(report.urllib.request, "urlopen",
                          return_value=Response()) as urlopen:
            result = report.publish_cms("# report\n", "20261117", "summary")

        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertTrue(request.full_url.endswith("/report"))
        self.assertEqual(body["slug"], "fleet-jobs-report")
        self.assertEqual(body["content_md"], "# report\n")
        self.assertEqual(result["slug"], "fleet-jobs-report")

    def test_claim_read_uses_compact_paginated_projection(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps(self.payload).encode()

        pages = [
            {"ok": True, "cards": [
                {"action": {"status": "running", "runner": "idc02"}}
            ], "truncated": True},
            {"ok": True, "cards": [
                {"action": {"status": "queued"}}
            ], "truncated": False},
        ]
        with patch.object(report.urllib.request, "urlopen",
                          side_effect=[Response(p) for p in pages]) as urlopen:
            stats = report.read_claim_stats()

        self.assertEqual(stats["running"], 1)
        self.assertEqual(stats["queued"], 1)
        self.assertIn("fields=id,action", urlopen.call_args_list[0].args[0])
        self.assertIn("offset=1", urlopen.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
