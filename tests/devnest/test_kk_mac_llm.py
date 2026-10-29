import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.devnest.kk_mac_llm import run_task, validate_task


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

    def test_remote_call_is_read_only_and_structured(self):
        class FakeRun:
            def __call__(self, command, **kwargs):
                self.command = command
                self.kwargs = kwargs
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        "response": "short summary",
                        "eval_count": 12,
                    }).encode(),
                    stderr=b"",
                )

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
        self.assertIn("--data-binary", " ".join(fake.command))
        self.assertNotIn("shell", fake.kwargs)
        self.assertEqual(result["usage"]["eval_count"], 12)


if __name__ == "__main__":
    unittest.main()
