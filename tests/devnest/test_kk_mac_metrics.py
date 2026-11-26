import json
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.devnest import kk_mac_metrics as km


LSL = """\
1000 2023-11-14 22:13:20.000000000 pack-a/pack.yml
500 2023-11-14 22:13:30.000000000 pack-a/inputs/task.json
10 2023-11-14 22:13:40.000000000 pack-a/done
900 2023-11-14 22:13:41.000000000 pack-a/out/result.json
800 2023-11-14 22:15:00.000000000 pack-a/claim/worker-1
900 2023-11-14 22:13:20.000000000 pack-b/pack.yml
10 2023-11-14 22:14:10.000000000 pack-b/failed
800 2023-11-14 22:13:20.000000000 pack-c/pack.yml
400 2023-11-14 22:13:50.000000000 pack-c/out/partial.json
10 2023-11-14 22:14:00.000000000 stray-top-level-file
"""


class ParseTests(unittest.TestCase):
    def test_parse_lsl_groups_by_pack(self):
        packs = km.parse_lsl(LSL)
        self.assertEqual(set(packs), {"pack-a", "pack-b", "pack-c"})
        self.assertIn("out/result.json", packs["pack-a"])

    def test_pack_metrics_status_and_wait(self):
        packs = km.parse_lsl(LSL)
        a = km.pack_metrics(packs["pack-a"])
        self.assertEqual(a["status"], "done")
        self.assertEqual(a["worker"], "worker-1")
        # staged_at = earliest file mtime (pack.yml @1700000000),
        # claimed @1700000100 -> wait 100s
        self.assertEqual(a["queue_wait_s"], 100.0)
        b = km.pack_metrics(packs["pack-b"])
        self.assertEqual(b["status"], "failed")
        self.assertIsNone(b["queue_wait_s"])  # no claim dir
        c = km.pack_metrics(packs["pack-c"])
        self.assertEqual(c["status"], "live")

    def test_fallback_status_and_terminal_precedence(self):
        files = {"pack.yml": (1700000000.0, 800),
                 "fallback": (1700000100.0, 10)}
        m = km.pack_metrics(files)
        self.assertEqual(m["status"], "fallback")
        # a terminal marker outranks a stale fallback hold
        files["done"] = (1700000200.0, 10)
        m = km.pack_metrics(files)
        self.assertEqual(m["status"], "done")
        files2 = {"pack.yml": (1700000000.0, 800),
                  "fallback": (1700000100.0, 10),
                  "failed": (1700000200.0, 10)}
        self.assertEqual(km.pack_metrics(files2)["status"], "failed")


class CollectTests(unittest.TestCase):
    def test_collect_counts_and_wait_stats(self):
        orig = km.rclone
        km.rclone = lambda *a: LSL
        try:
            out = km.collect(with_tokens=False)
        finally:
            km.rclone = orig
        self.assertEqual(out["packs"],
                         {"total": 3, "done": 1, "failed": 1,
                          "fallback": 0, "live": 1})
        self.assertEqual(out["interventions"], 1)
        self.assertEqual(out["queue_wait_seconds"]["n"], 1)
        self.assertEqual(out["queue_wait_seconds"]["mean"], 100.0)

    def test_collect_tokens(self):
        result = {"verified": True, "eval_count": 65,
                  "eval_duration": 1056496000, "load_duration": 807884375,
                  "wall_seconds": 2.5}
        cats = []

        def fake_cat(path):
            cats.append(path)
            return json.dumps(result)

        orig = km.rclone
        km.rclone = lambda *a: LSL
        try:
            out = km.collect(with_tokens=True, cat=fake_cat)
        finally:
            km.rclone = orig
        t = out["tokens"]
        self.assertEqual(t["result_files"], 2)  # done + failed packs
        self.assertEqual(t["verified"], 2)
        self.assertEqual(t["eval_count_total"], 130)
        self.assertAlmostEqual(t["eval_duration_s_total"], 2.1, places=1)
        self.assertEqual(out["wall_seconds"]["mean"], 2.5)
        self.assertTrue(all("result.json" in c for c in cats))


class WindowTests(unittest.TestCase):
    def test_window_scopes_counts_and_token_fetch(self):
        result = {"verified": True, "eval_count": 10,
                  "eval_duration": 1e9, "wall_seconds": 1.0}
        cats = []

        def fake_cat(path):
            cats.append(path)
            return json.dumps(result)

        orig = km.rclone
        km.rclone = lambda *a: LSL
        try:
            # now=1700000100, window 120s -> cutoff 1699999980: every
            # pack staged @1700000000 is inside (live pack-c counts via
            # staged_at; its live status keeps it out of the cat path).
            out = km.collect(with_tokens=True, cat=fake_cat,
                             window_s=120, now=1700000100)
            # tight window: cutoff 1700000050 leaves only pack-b
            # (failed marker lands exactly on the cutoff).
            tight = km.collect(with_tokens=True, cat=lambda p: "{}",
                               window_s=50, now=1700000100)
        finally:
            km.rclone = orig
        w = out["window"]
        self.assertEqual(w["packs"],
                         {"total": 3, "done": 1, "failed": 1,
                          "fallback": 0, "live": 1})
        self.assertEqual(w["interventions"], 1)
        self.assertEqual(w["tokens"]["result_files"], 2)
        self.assertTrue(all("pack-c" not in c for c in cats))
        # lifetime block stays listing-only — no top-level tokens
        self.assertNotIn("tokens", out)
        self.assertEqual(tight["window"]["packs"],
                         {"total": 1, "done": 0, "failed": 1,
                          "fallback": 0, "live": 0})

    def test_window_without_tokens_has_no_cats(self):
        orig = km.rclone
        km.rclone = lambda *a: LSL
        try:
            out = km.collect(window_s=50, now=1700000100)
        finally:
            km.rclone = orig
        self.assertEqual(out["window"]["packs"]["total"], 1)
        self.assertNotIn("tokens", out["window"])


class PublishTests(unittest.TestCase):
    def _out(self, failed=0):
        return {
            "generated_at": "2026-11-26T00:00:00+00:00",
            "remote": km.REMOTE,
            "packs": {"total": 4, "done": 3, "failed": failed,
                      "fallback": 0, "live": 1},
            "interventions": failed,
            "queue_wait_seconds": {"n": 0},
            "staged_to_done_seconds": {"n": 0},
            "wall_seconds": {"n": 0},
            "window": {
                "seconds": 604800,
                "since": "2026-11-19T00:00:00+00:00",
                "packs": {"total": 2, "done": 2, "failed": failed,
                          "fallback": 0, "live": 0},
                "interventions": failed,
            },
        }

    def test_publish_writes_artifact_and_meta(self):
        with tempfile.TemporaryDirectory() as td:
            res = km.publish(self._out(failed=0), out_dir=Path(td),
                             generated_by="test")
            artifact = json.loads(
                (Path(td) / "kk-llm-metrics.json").read_text())
            self.assertEqual(artifact["packs"]["done"], 3)
            meta = yaml.safe_load(
                (Path(td) / "meta.kk-llm.yml").read_text())
            self.assertEqual(meta["node"], "nest-lanes/kk-llm")
            self.assertEqual(meta["layer"], "L1-producer")
            self.assertEqual(meta["status"], "ok")
            self.assertIn("3 done", meta["summary"])
            self.assertEqual(res["meta"],
                             str(Path(td) / "meta.kk-llm.yml"))

    def test_publish_delta_on_window_failure(self):
        with tempfile.TemporaryDirectory() as td:
            km.publish(self._out(failed=1), out_dir=Path(td),
                       generated_by="test")
            meta = yaml.safe_load(
                (Path(td) / "meta.kk-llm.yml").read_text())
            self.assertEqual(meta["status"], "delta")


if __name__ == "__main__":
    unittest.main()
