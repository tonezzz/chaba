import inspect
import json
import unittest
from unittest.mock import patch

from scripts.devnest import (
    devnest_capacity_broker as broker,
    devnest_report_feed as report_feed,
    kk_mac_capacity_producer as producer,
    kk_mac_metrics as metrics,
    kk_mac_plan_validator as validator,
)


class GdriveRootTests(unittest.TestCase):
    def test_broker_defaults_use_consolidated_roots(self):
        self.assertEqual(
            inspect.signature(broker.produce).parameters["source"].default,
            "gdrive:ada-nest/devnest",
        )
        self.assertEqual(
            inspect.signature(broker.produce).parameters["kk_remote"].default,
            "gdrive:ada-nest/kk-llm",
        )
        self.assertEqual(broker.DEVNEST_REMOTE, "gdrive:ada-nest/devnest")
        self.assertEqual(broker.KK_LLM_REMOTE, "gdrive:ada-nest/kk-llm")

    def test_devnest_consumers_use_consolidated_root(self):
        self.assertEqual(report_feed.REMOTE, "gdrive:ada-nest/devnest")
        self.assertEqual(
            validator.DEFAULT_REMOTE,
            "gdrive:ada-nest/devnest",
        )

    def test_kk_consumers_use_consolidated_root(self):
        self.assertEqual(producer.DEFAULT_REMOTE, "gdrive:ada-nest/kk-llm")
        self.assertEqual(metrics.REMOTE, "gdrive:ada-nest/kk-llm")

    def test_broker_routes_canary_between_consolidated_roots(self):
        spec = {
            "task_id": "canary-task-1",
            "lane": "kk_mac_local",
            "task_class": "summary",
            "prompt": "summarize canary evidence",
        }
        calls = []

        def fake_rc(*args, input_text=None):
            calls.append((args, input_text))
            if args[0] == "lsf":
                return "canary-task-1.json\n"
            if args[0] == "cat":
                return json.dumps(spec)
            return ""

        with (
            patch.object(broker, "snapshot", return_value={"eligible": True}),
            patch.object(broker, "rc", side_effect=fake_rc),
        ):
            result = broker.produce()

        source_inbox = "gdrive:ada-nest/devnest/inbox"
        target = "gdrive:ada-nest/kk-llm/inbox/canary-task-1.json"
        self.assertEqual(result["source"], "gdrive:ada-nest/devnest")
        self.assertEqual(result["routed"][0]["destination"], target)
        # routing writes the NORMALIZED envelope to <task_id>.json
        routed_writes = [
            (args, body) for args, body in calls
            if args[:2] == ("rcat", target)
        ]
        self.assertEqual(len(routed_writes), 1)
        written = json.loads(routed_writes[0][1])
        self.assertEqual(written["task_id"], "canary-task-1")
        self.assertEqual(written["timeout_s"], 600)
        self.assertTrue(any(
            args[:2] == ("rcat", f"{source_inbox}/canary-task-1.json.routed")
            for args, _ in calls
        ))


if __name__ == "__main__":
    unittest.main()
