"""tests/board/test_board_api_jobs_evidence.py — read-only evidence endpoints
(KNB-0229 design §4): GET /jobs (card or job_id) returns the DevNest lane
metric + runner usage.json + committed envelope per job — the read door the
control pane uses for tokens/cost/duration.

Pattern follows test_board_api_reads.py: importlib load of board-api.py,
ThreadingHTTPServer on an ephemeral port, mocked state dirs — no network
beyond loopback.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "board_api_jobs", REPO / "scripts" / "board" / "board-api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LaneEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_lane_metrics_filter_card_and_order_latest_first(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "metrics.jsonl").write_text("\n".join([
                json.dumps({"job_id": "j1", "card": "c-one",
                            "at": "2026-11-19 10:00", "input_tokens": 10}),
                json.dumps({"job_id": "j2", "card": "c-one",
                            "at": "2026-11-19 09:00"}),
                json.dumps({"job_id": "j3", "card": "c-two",
                            "at": "2026-11-19 11:00"}),
                "{not json",
            ]) + "\n")
            with mock.patch.dict(os.environ, {"OPENCODE_LANE_STATE": td}):
                got = self.mod._lane_metrics(card_id="c-one")
                self.assertEqual([m["job_id"] for m in got], ["j1", "j2"])
                self.assertEqual(got[0]["input_tokens"], 10)
                self.assertEqual(
                    self.mod._lane_metrics(job_id="j3")[0]["card"], "c-two")

    def test_lane_metrics_empty_without_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"OPENCODE_LANE_STATE": td}):
                self.assertEqual(self.mod._lane_metrics(card_id="c-one"), [])

    def test_usage_for_job_reads_taskdir(self):
        mod = self.mod
        with tempfile.TemporaryDirectory() as td:
            tasks = Path(td, "tasks", "j1")
            tasks.mkdir(parents=True)
            Path(tasks, "usage.json").write_text(json.dumps(
                {"input_tokens": 10, "output_tokens": 5, "exit_code": 0}))
            with mock.patch.object(mod, "DISPATCH_TASKS", Path(td, "tasks")):
                self.assertEqual(mod._usage_for_job("j1")["input_tokens"], 10)
                self.assertEqual(mod._usage_for_job("nope"), {})
                self.assertEqual(mod._usage_for_job(""), {})

    def test_envelope_for_job_reads_committed_envelope(self):
        mod = self.mod
        with tempfile.TemporaryDirectory() as td:
            jobs = Path(td, "evals", "opencode-lane", "jobs")
            jobs.mkdir(parents=True)
            Path(jobs, "j1.yaml").write_text(
                "id: j1\njob_id: j1\nstate: draft\n")
            with mock.patch.object(mod, "REPO", Path(td)):
                self.assertEqual(mod._envelope_for_job("j1")["id"], "j1")
                self.assertIsNone(mod._envelope_for_job("j-missing"))
                self.assertIsNone(mod._envelope_for_job(""))

    def test_lane_evidence_merges_metric_usage_envelope(self):
        mod = self.mod
        with tempfile.TemporaryDirectory() as td:
            Path(td, "metrics.jsonl").write_text(json.dumps({
                "job_id": "j1", "card": "c-one", "at": "2026-11-19 10:00",
                "input_tokens": 10, "output_tokens": 5,
                "provider_cost_usd": 0.01, "wall_s": 12, "queue_s": 1,
            }) + "\n")
            tasks = Path(td, "tasks", "j1")
            tasks.mkdir(parents=True)
            Path(tasks, "usage.json").write_text(json.dumps(
                {"input_tokens": 10, "output_tokens": 5}))
            with mock.patch.dict(os.environ, {"OPENCODE_LANE_STATE": td}), \
                    mock.patch.object(mod, "DISPATCH_TASKS", Path(td, "tasks")):
                rows = mod._lane_evidence(card_id="c-one")
                self.assertEqual(len(rows), 1)
                job = rows[0]
                self.assertEqual(job["job_id"], "j1")
                self.assertEqual(job["input_tokens"], 10)
                self.assertEqual(job["provider_cost_usd"], 0.01)
                self.assertEqual(job["usage"]["output_tokens"], 5)
                self.assertEqual(mod._lane_evidence(card_id="c-none"), [])


class JobsRouteTest(unittest.TestCase):
    """do_GET /jobs over loopback with mocked state dirs."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()
        cls.tmp = tempfile.TemporaryDirectory()
        Path(cls.tmp.name, "metrics.jsonl").write_text(
            json.dumps({"job_id": "j1", "card": "c-one",
                        "at": "2026-11-19 10:00", "input_tokens": 10}) + "\n")
        cls.tasks = Path(cls.tmp.name, "tasks")
        (cls.tasks / "j1").mkdir(parents=True)
        Path(cls.tasks / "j1" / "usage.json").write_text(
            json.dumps({"input_tokens": 10}))
        cls._env = mock.patch.dict(
            os.environ, {"OPENCODE_LANE_STATE": cls.tmp.name})
        cls._env.start()
        cls._pat = mock.patch.object(cls.mod, "DISPATCH_TASKS", cls.tasks)
        cls._pat.start()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), cls.mod.H)
        cls.port = cls.srv.server_address[1]
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls._env.stop()
        cls._pat.stop()
        cls.tmp.cleanup()

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_jobs_by_card(self):
        st, body = self.get("/jobs?card=c-one")
        self.assertEqual(st, 200)
        self.assertTrue(body["ok"])
        self.assertEqual([j["job_id"] for j in body["jobs"]], ["j1"])
        self.assertEqual(body["jobs"][0]["card"], "c-one")
        self.assertEqual(body["jobs"][0]["usage"]["input_tokens"], 10)

    def test_jobs_by_job_id(self):
        st, body = self.get("/jobs?job_id=j1")
        self.assertEqual((st, body["jobs"][0]["job_id"]), (200, "j1"))

    def test_jobs_no_match(self):
        st, body = self.get("/jobs?card=c-missing")
        self.assertEqual((st, body["ok"], body["jobs"]), (200, True, []))

    def test_jobs_requires_card_or_job_id(self):
        st, body = self.get("/jobs")
        self.assertEqual(st, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
