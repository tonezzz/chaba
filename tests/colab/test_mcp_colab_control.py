"""Unit tests for the mcp-colab queue-start command gate."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "mcp-servers/mcp-colab/server.py"
BOOT = "e115005b-b512-4d29-8b76-80bc30f853c3"


class FakeFastMCP:
    def __init__(self, _name):
        pass

    def tool(self):
        return lambda fn: fn


def load_server():
    fake_mcp = types.ModuleType("mcp")
    fake_server = types.ModuleType("mcp.server")
    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp.FastMCP = FakeFastMCP
    modules = {
        "mcp": fake_mcp,
        "mcp.server": fake_server,
        "mcp.server.fastmcp": fake_fastmcp,
    }
    spec = importlib.util.spec_from_file_location("mcp_colab_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class TestColabQueueStart(unittest.TestCase):
    def setUp(self):
        self.server = load_server()
        self.record = {
            "boot_id": BOOT,
            "kind": "managed-notebook",
            "ts": time.time(),
            "gpu": "Tesla T4",
            "gpu_gb": 15,
            "drive_mounted": True,
        }
        self.captured = {}

    def fake_rclone(self, *args, **_kwargs):
        op = args[0]
        if op == "mkdir":
            return 0, ""
        if op == "lsf":
            return 0, f"{BOOT}.json"
        if op == "cat":
            path = args[1]
            if path.endswith(f"{BOOT}.json"):
                return 0, json.dumps(self.record)
            if path.endswith("/runner.id"):
                if self.captured.get("runner_id"):
                    return 0, json.dumps(self.captured["runner_id"])
                return 3, "not found"
            if path.endswith("/heartbeat"):
                return 0, f"{time.time() - 3600:.0f} idle exit"
            if path.endswith("/lease"):
                return 0, json.dumps({
                    "worker": "old-worker", "epoch": 4,
                    "ts": time.time() - 3600,
                })
            if path == self.captured.get("ack_path"):
                return 0, json.dumps(self.captured["ack"])
            return 3, "not found"
        if op == "copyto":
            payload = json.loads(Path(args[1]).read_text())
            self.captured["request"] = payload
            self.captured["ack_path"] = args[2].replace("/requests/", "/acks/")
            self.captured["ack"] = {
                "request_id": payload["request_id"],
                "target_boot_id": BOOT,
                "status": "started",
                "message": "queue pid 123",
            }
            return 0, ""
        raise AssertionError(f"unexpected rclone operation: {args}")

    def test_requires_explicit_confirmation_before_drive_io(self):
        with patch.object(self.server, "_rclone") as rclone:
            result = self.server.colab_queue_start(BOOT, confirm=False)
        self.assertIn("REFUSED", result)
        rclone.assert_not_called()

    def test_stale_runtime_refused_without_queue_request(self):
        self.record["ts"] = time.time() - 600
        with patch.object(self.server, "_rclone", side_effect=self.fake_rclone):
            result = self.server.colab_queue_start(BOOT, confirm=True)
        self.assertIn("stale", result)
        self.assertNotIn("request", self.captured)

    def test_existing_runner_refused(self):
        self.captured["runner_id"] = {
            "pid": 123, "boot_id": BOOT, "worker": "current-worker",
            "epoch": 2, "ts": time.time(),
        }
        with patch.object(self.server, "_rclone", side_effect=self.fake_rclone):
            result = self.server.colab_queue_start(BOOT, confirm=True)
        self.assertIn("runner.id is present", result)
        self.assertNotIn("request", self.captured)

    def test_fresh_runtime_gets_targeted_request_and_ack(self):
        with patch.object(self.server, "_rclone", side_effect=self.fake_rclone):
            result = self.server.colab_queue_start(BOOT, confirm=True)
            status = self.server.colab_queue_request_status(
                self.captured["request"]["request_id"])
        self.assertIn("started", result)
        self.assertEqual(self.captured["request"]["command"], "start_queue")
        self.assertTrue(self.captured["request"]["confirmed"])
        self.assertEqual(self.captured["request"]["target_boot_id"], BOOT)
        self.assertIn("started", status)

    def test_session_status_formats_legacy_record_without_epoch_overflow(self):
        legacy = {
            "boot_id": BOOT,
            "last_seen": time.time() - 3600,
            "gpu": {"name": "Tesla T4", "memory_mib": 15360, "used_mib": 0},
            "drive_mounted": True,
        }

        def fake_rclone(*args, **_kwargs):
            if args[0] == "cat":
                path = args[1]
                if path.endswith("/heartbeat"):
                    return 0, f"{time.time() - 3600:.0f} old-job exit"
                if path.endswith("/lease"):
                    return 0, json.dumps({"worker": "old", "epoch": 1,
                                         "ts": time.time() - 3600})
                if path.endswith("/runner.id"):
                    return 3, "not found"
                return 3, "not found"   # ACTIVE_RELEASE.json etc.
            raise AssertionError(f"unexpected rclone operation: {args}")

        with patch.object(
                self.server, "_runtime_records",
                return_value=([legacy], "")), patch.object(
                    self.server, "_rclone", side_effect=fake_rclone):
            result = self.server.colab_session_status()
        self.assertIn(BOOT, result)
        self.assertIn("Tesla T4 15.0GB", result)
        self.assertIn("STALE 60min", result)
        self.assertNotIn("unknownmin", result)


if __name__ == "__main__":
    unittest.main()
