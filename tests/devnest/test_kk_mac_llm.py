import base64
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.devnest.kk_mac_llm import run_task, validate_task


def _guard_stdout(**over):
    out = {"ok": True, "verdict": "ok", "reason": "",
           "response": "short summary", "eval_count": 12,
           "eval_duration": 100, "load_duration": 50,
           "memory": {"pre_pct": 72.0, "min_during_pct": 55.0,
                      "post_pct": 60.0, "loaded_by_task": True,
                      "unloaded": True},
           "guard": "kk_mac_remote_guard/1"}
    out.update(over)
    return json.dumps(out).encode()


class KkMacLlmTests(unittest.TestCase):
    def test_rejects_unadmitted_task(self):
        with self.assertRaises(ValueError):
            validate_task("code_mutation", "edit the repository")

    def test_rejects_large_prompt(self):
        with self.assertRaises(ValueError):
            validate_task("summary", "x" * 6001)

    def test_fails_closed_when_heartbeat_gate_denies(self):
        with patch(
            "scripts.devnest.kk_mac_llm.snapshot",
            return_value={
                "eligible": False,
                "reasons": ["heartbeat_stale"],
            },
        ):
            result = run_task("summary", "summarize this")
        self.assertFalse(result["ok"])
        self.assertEqual(result["admission"]["reasons"], ["heartbeat_stale"])

    def test_remote_call_ships_guard_with_floors(self):
        class FakeRun:
            def __call__(self, command, **kwargs):
                self.command = command
                self.kwargs = kwargs
                return subprocess.CompletedProcess(
                    command, 0, stdout=_guard_stdout(), stderr=b"")

        fake = FakeRun()
        with patch(
            "scripts.devnest.kk_mac_llm.snapshot",
            return_value={"eligible": True, "reasons": []},
        ):
            result = run_task(
                "summary",
                "summarize this",
                ssh_run=fake,
            )
        self.assertTrue(result["ok"])
        # guard path: python3 - <b64 payload>, script on stdin
        self.assertEqual(fake.command[-3], "python3")
        self.assertEqual(fake.command[-2], "-")
        inner = json.loads(base64.b64decode(fake.command[-1]))
        self.assertEqual(inner["model"], "qwen3:8b")
        self.assertEqual(inner["entry_floor_pct"], 60.0)
        self.assertEqual(inner["abort_floor_pct"], 50.0)
        self.assertTrue(inner["unload_after"])
        self.assertIn(b"kk_mac_remote_guard", fake.kwargs["input"])
        self.assertEqual(result["usage"]["eval_count"], 12)
        self.assertEqual(result["memory"]["pre_pct"], 72.0)
        self.assertEqual(result["guard"], "kk_mac_remote_guard/1")

    def test_guard_decline_surfaces_verdict(self):
        class FakeRun:
            def __call__(self, command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 2,
                    stdout=_guard_stdout(
                        ok=False, verdict="memory_abort",
                        reason="free memory fell below abort floor 50%",
                        response=""),
                    stderr=b"")

        with patch(
            "scripts.devnest.kk_mac_llm.snapshot",
            return_value={"eligible": True, "reasons": []},
        ):
            result = run_task("summary", "summarize this",
                              ssh_run=FakeRun())
        self.assertFalse(result["ok"])
        self.assertEqual(result["verdict"], "memory_abort")
        joined = ";".join(result["admission"]["reasons"])
        self.assertIn("guard:memory_abort", joined)
        self.assertEqual(result["guard"]["pre_pct"], 72.0)

    def test_non_json_remote_output_raises(self):
        class FakeRun:
            def __call__(self, command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 1, stdout=b"", stderr=b"ssh: denied")

        with patch(
            "scripts.devnest.kk_mac_llm.snapshot",
            return_value={"eligible": True, "reasons": []},
        ):
            with self.assertRaises(RuntimeError):
                run_task("summary", "summarize this", ssh_run=FakeRun())


if __name__ == "__main__":
    unittest.main()
