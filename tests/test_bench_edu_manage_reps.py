"""Multi-repetition benchmark reports must summarize every run."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts/ada"))
spec = importlib.util.spec_from_file_location(
    "bench_edu_manage", REPO / "scripts/bench-edu-manage.py")
bench = importlib.util.module_from_spec(spec)
sys.modules["bench_edu_manage"] = bench
spec.loader.exec_module(bench)


def rep(f1: float, dedupe: int, ops: int, recall: int,
        completed: int, p50: float) -> dict:
    return {
        "capture": {"f1": f1, "precision": 1.0, "recall": f1},
        "dedupe": {"correct": dedupe, "total": 5, "score": dedupe / 5},
        "sched_ops": {"pass": ops, "total": 5},
        "recall": {"correct": recall, "total": 3},
        "draft_quality": None,
        "loop": {
            "completed": completed, "total": 13, "lat_p50": p50,
            "tokens_in": 1000, "tokens_out": 200, "arg_repairs": 0,
            "arg_errors": 0, "json_retries": 0, "json_mode": True,
        },
    }


class MultiRepReport(unittest.TestCase):
    def test_cli_can_pin_the_openrouter_model(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts/bench-edu-manage.py"),
             "--help"],
            capture_output=True, text=True, check=True)
        self.assertIn("--or-model", result.stdout)

    def test_summary_includes_all_repetitions_and_task_rep_numbers(self):
        result = {
            "date": "2026-10-24",
            "config": {"lanes": {}},
            "scores": {"clawbot": [
                rep(1.0, 4, 5, 3, 13, 12.9),
                rep(1.0, 5, 5, 3, 13, 15.5),
                rep(0.8, 3, 4, 2, 12, 22.0),
            ]},
            "tasks": {"clawbot": [
                {"rep": 1, "task": "t1", "completed": True,
                 "tool_calls": 1, "llm_calls": 2, "latency": 12.9},
                {"rep": 2, "task": "t1", "completed": True,
                 "tool_calls": 1, "llm_calls": 2, "latency": 15.5},
                {"rep": 3, "task": "t1", "completed": False,
                 "tool_calls": 0, "llm_calls": 1, "latency": 22.0,
                 "err": "HTTP 500"},
            ]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi.md"
            bench.write_md(path, result)
            output = path.read_text()
        self.assertIn("F1 mean [range]", output)
        self.assertIn("| clawbot | 3 | 0.93 [0.80-1.00]", output)
        self.assertIn("## Per-repetition summary", output)
        self.assertIn("| clawbot | 3 | 0.8 | 3/5 | 4/5 | 2/3 | 12/13 | 22.0s |",
                      output)
        self.assertIn("rep=3 `t1` completed=False", output)


if __name__ == "__main__":
    unittest.main()
