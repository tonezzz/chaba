import unittest
from unittest.mock import patch, mock_open, MagicMock
import json
import os
import sys

# Ensure scripts directory is in path to import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts/ada')))

# Import using runpy since it's a script not directly packaged
import importlib.util
spec = importlib.util.spec_from_file_location("consultant_bench", "scripts/ada/consultant-bench.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

class TestConsultantBench(unittest.TestCase):

    def test_parse_fixture(self):
        fixture_data = '{"id": "c1", "task": "t1", "expected": "answer"}\n{"id": "c2", "task": "t2", "expected": "escalate"}\n'
        with patch('builtins.open', mock_open(read_data=fixture_data)):
            tasks = cb.parse_fixture('dummy.jsonl')
            self.assertEqual(len(tasks), 2)
            self.assertEqual(tasks[0]["id"], "c1")
            self.assertEqual(tasks[1]["expected"], "escalate")

    @patch('urllib.request.urlopen')
    def test_ask_litellm_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Answer "}}]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_response

        res, ms = cb.ask_litellm("dummy-model", "test task")
        self.assertEqual(res["decision"], "answer")
        self.assertGreaterEqual(ms, 0)

    @patch('urllib.request.urlopen')
    def test_ask_litellm_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection Error")

        res, ms = cb.ask_litellm("dummy-model", "test task")
        self.assertIn("_err", res)
        self.assertEqual(res["_err"], "Connection Error")
        self.assertGreaterEqual(ms, 0)

    def test_write_reports(self):
        summary = {
            "accuracy": 0.5,
            "lat_p50_ms": 100.0,
            "escalation_rate": 0.5,
            "total": 2,
            "correct": 1
        }
        records = [
            {"id": "1", "expected": "answer", "got": "answer", "ok": True, "ms": 90},
            {"id": "2", "expected": "escalate", "got": "answer", "ok": False, "ms": 110}
        ]

        with patch('builtins.open', mock_open()) as mocked_file:
            cb.write_reports("dummy-model", records, summary)

            # Should have opened .json and .md files
            self.assertEqual(mocked_file.call_count, 2)
            calls = mocked_file.call_args_list
            self.assertTrue("reports/consultant-bench-dummy-model.json" in calls[0][0][0])
            self.assertTrue("reports/consultant-bench-dummy-model.md" in calls[1][0][0])

if __name__ == '__main__':
    unittest.main()
