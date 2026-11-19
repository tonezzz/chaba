"""Unit tests for mcp-debug SSOT registry and table formatters.

Covers scripts/mcp_debug/registry.py (asset-oriented lookup over the
partitioned SSOT registry) and scripts/mcp_debug/formatters.py
(compact-JSON -> CSV/proxy-envelope table conversion).
"""

from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.mcp_debug import formatters, registry, ssot  # noqa: E402


DF_COMPACT = {
    "ok": True,
    "fs": [{"f": "/dev/sda1", "s": "100G", "u": "10G", "a": "90G", "m": "5%", "p": "/"}],
}

MOUNT_COMPACT = {
    "ok": True,
    "m": [{"d": "/dev/sda1", "p": "/", "t": "ext4", "o": "rw,relatime"}],
}


def _temp_usage_log(dirpath):
    usage = Path(dirpath) / "mcp-usage.ndjson"
    usage.touch()
    return usage


class RepoRegistryTests(unittest.TestCase):
    """Read-only assertions against the real chaba SSOT registry."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="mcp-debug-usage-")
        self.addCleanup(tmp.cleanup)
        patcher = patch.object(ssot, "_USAGE_LOG", _temp_usage_log(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_tools_asset_by_id(self):
        res = registry.mcp_registry_get(id="mcp-debug-tools", ssot_limit=100000)
        self.assertTrue(res["ok"])
        self.assertEqual(res["asset"]["id"], "mcp-debug-tools")
        self.assertEqual(res["asset"]["path"], "scripts/mcp_debug/tools.py")
        self.assertEqual(res["ssot"]["path"], "scripts/mcp_debug/tools.py")
        self.assertIn("MCP Debug tool functions", res["ssot"]["content"])
        self.assertFalse(res["ssot"]["truncated"])

    def test_lookup_by_path_finds_server_asset(self):
        res = registry.mcp_registry_lookup(q="mcp_debug/server.py", by="path", type="script")
        self.assertTrue(res["ok"])
        paths = [a["path"] for a in res["results"]]
        self.assertIn("scripts/mcp_debug/server.py", paths)
        asset = next(a for a in res["results"] if a["path"] == "scripts/mcp_debug/server.py")
        self.assertEqual(asset["id"], "mcp-debug-server")
        self.assertEqual(asset["status"], "active")

    def test_lookup_by_tags(self):
        res = registry.mcp_registry_lookup(q="mcp", by="tags", type="script", limit=231)
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["total"], 1)
        ids = [a["id"] for a in res["results"]]
        self.assertIn("mcp-debug-tools", ids)

    def test_lookup_without_query_lists_assets(self):
        res = registry.mcp_registry_lookup(limit=1)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["results"]), 1)
        self.assertGreater(res["total"], 0)
        for a in res["results"]:
            for key in ("id", "name", "type", "path", "purpose", "status"):
                self.assertTrue(a.get(key), f"missing or empty {key}")

    def test_lookup_pagination(self):
        page1 = registry.mcp_registry_lookup(limit=1, offset=0)
        page2 = registry.mcp_registry_lookup(limit=1, offset=1)
        self.assertEqual(page1["limit"], 1)
        self.assertEqual(page2["offset"], 1)
        if page1["total"] >= 2:
            self.assertEqual(len(page1["results"]), 1)
            self.assertEqual(len(page2["results"]), 1)

    def test_get_requires_id_or_path(self):
        res = registry.mcp_registry_get()
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "id or path is required")

    def test_get_unknown_id(self):
        res = registry.mcp_registry_get(id="definitely-not-an-asset")
        self.assertFalse(res["ok"])
        self.assertIn("no asset found", res["error"])


class RegistryFixtureTests(unittest.TestCase):
    """Hermetic tests against a temp registry fixture (REPO_DIR patched)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="mcp-debug-registry-fixture-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ssot_dir = root / "docs" / "ssot"
        ssot_dir.mkdir(parents=True)
        (ssot_dir / "ssot.registry.yml").write_text(
            "title: Registry\nassets:\n"
            "  - path: docs/ssot/ssot.registry.p1.yml\n"
            "  - path: docs/ssot/ssot.registry.p2.yml\n"
        )
        (ssot_dir / "ssot.registry.p1.yml").write_text(
            yaml.safe_dump({
                "title": "P1",
                "assets": [
                    {"id": "dup-asset", "name": "a.yml", "type": "ssot",
                     "path": "docs/ssot/p1.yml", "purpose": "first", "status": "active",
                     "tags": ["x", "shared"]},
                    {"id": "p1-only", "name": "p1-only", "type": "ssot",
                     "path": "docs/ssot/p1b.yml", "purpose": "first only", "status": "active"},
                ],
            })
        )
        (ssot_dir / "ssot.registry.p2.yml").write_text(
            yaml.safe_dump({
                "title": "P2",
                "assets": [
                    {"id": "dup-asset", "name": "b.yml", "type": "ssot",
                     "path": "docs/ssot/p2.yml", "purpose": "second", "status": "active"},
                ],
            })
        )
        (ssot_dir / "p1.yml").write_text("title: P1\nvalue: one\n")
        (ssot_dir / "p2.yml").write_text("title: P2\nvalue: two\n")
        (ssot_dir / "p1b.yml").write_text("title: P1B\nvalue: oneb\n")
        patchers = [
            patch.object(registry, "REPO_DIR", root),
            patch.object(ssot, "REPO_DIR", root),
            patch.object(ssot, "_USAGE_LOG", _temp_usage_log(tmp.name)),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_lookup_lists_all_when_no_query(self):
        res = registry.mcp_registry_lookup()
        self.assertTrue(res["ok"])
        self.assertEqual(sorted(a["id"] for a in res["results"]), ["dup-asset", "dup-asset", "p1-only"])
        self.assertEqual(res["total"], 3)

    def test_lookup_by_tags(self):
        res = registry.mcp_registry_lookup(q="shared", by="tags")
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["results"][0]["id"], "dup-asset")

    def test_lookup_pagination(self):
        page2 = registry.mcp_registry_lookup(limit=1, offset=2)
        self.assertTrue(page2["ok"])
        self.assertEqual(page2["offset"], 2)
        self.assertLessEqual(len(page2["results"]), 1)

    def test_get_ambiguous_id_reports_candidates(self):
        res = registry.mcp_registry_get(id="dup-asset")
        self.assertFalse(res["ok"])
        self.assertIn("multiple assets match 'dup-asset'", res["error"])
        self.assertEqual(len(res["candidates"]), 2)

    def test_get_by_path_disambiguates(self):
        res = registry.mcp_registry_get(id="dup-asset", path="docs/ssot/p2.yml")
        self.assertTrue(res["ok"])
        self.assertEqual(res["asset"]["name"], "b.yml")
        self.assertEqual(res["ssot"]["path"], "docs/ssot/p2.yml")
        self.assertEqual(res["ssot"]["content"], "title: P2\nvalue: two\n")

    def test_get_by_path_unique(self):
        res = registry.mcp_registry_get(path="docs/ssot/p1.yml")
        self.assertTrue(res["ok"])
        self.assertEqual(res["asset"]["id"], "dup-asset")
        self.assertEqual(res["ssot"]["content"], "title: P1\nvalue: one\n")

    def test_get_unknown_id(self):
        res = registry.mcp_registry_get(id="ghost-id")
        self.assertFalse(res["ok"])
        self.assertIn("no asset found", res["error"])

    def test_safe_path_rejects_escapes(self):
        root = Path(registry.REPO_DIR)
        self.assertIsNone(registry._safe_path("../outside.yml"))
        self.assertIsNone(ssot._safe_path("../outside.yml"))
        self.assertEqual(registry._safe_path("docs/ssot/p2.yml"), root / "docs" / "ssot" / "p2.yml")

    def test_get_with_key_query(self):
        res = registry.mcp_registry_get(path="docs/ssot/p2.yml", key="value")
        self.assertTrue(res["ok"])
        self.assertEqual(res["ssot"]["query_result"]["type"], "str")
        self.assertEqual(res["ssot"]["query_result"]["value"], "two")

    def test_get_requires_id_or_path(self):
        res = registry.mcp_registry_get()
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "id or path is required")


class FormatterTests(unittest.TestCase):
    def test_to_csv_filesystems(self):
        res = formatters.to_csv("df -h", DF_COMPACT)
        self.assertTrue(res["ok"])
        self.assertEqual(res["expected"], "filesystems")
        self.assertIn("Filesystem,Size,Used,Available,UsePercent,Mount", res["csv"])
        self.assertIn("/dev/sda1,100G,10G,90G,5%,/", res["csv"])

    def test_to_csv_mounts_uses_array_key(self):
        res = formatters.to_csv("mount", MOUNT_COMPACT)
        self.assertTrue(res["ok"])
        rows = list(csv.reader(io.StringIO(res["csv"])))
        self.assertEqual(rows[0], ["Device", "Path", "Type", "Options"])
        self.assertEqual(rows[1], ["/dev/sda1", "/", "ext4", "rw,relatime"])

    def test_to_csv_error_when_command_not_ok(self):
        res = formatters.to_csv("df -h", {"ok": False, "error": "host unreachable"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "host unreachable")

    def test_to_csv_error_when_no_schema(self):
        res = formatters.to_csv("not-a-table-command", {"ok": True})
        self.assertFalse(res["ok"])
        self.assertIn("no table schema", res["error"])

    def test_to_csv_error_when_no_array(self):
        res = formatters.to_csv("df -h", {"ok": True})
        self.assertFalse(res["ok"])
        self.assertIn("no table array found", res["error"])

    def test_to_envelope_roundtrip(self):
        env = formatters.to_envelope("df -h", DF_COMPACT)
        self.assertTrue(env["ok"])
        self.assertEqual(
            env["headers"],
            ["Filesystem", "Size", "Used", "Available", "UsePercent", "Mount"],
        )
        self.assertEqual(env["rows"], [["/dev/sda1", "100G", "10G", "90G", "5%", "/"]])

    def test_to_envelope_empty_rows(self):
        env = formatters.to_envelope("df -h", {"ok": True, "fs": []})
        self.assertTrue(env["ok"])
        self.assertEqual(env["headers"], ["Filesystem", "Size", "Used", "Available", "UsePercent", "Mount"])
        self.assertEqual(env["rows"], [])


if __name__ == "__main__":
    unittest.main()
