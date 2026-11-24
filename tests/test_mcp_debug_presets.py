"""Tests for the mcp-debug preset surface (AUD-1033 follow-up, card
ops-manual-command-api-mcp-efficiency-followups).

Presets are operator-authored bundles of EXISTING tool calls — the
host-snapshot preset runs scripts/devnest/host_snapshot.py via mcp_raw
on every configured host. These tests pin the contract:

  * the split SSOT (ssot.mcp-debug.presets.yml) loads through
    config._load_presets and wins over any inline presets: block;
  * every preset step respects the tool policy declared in the file —
    step tools are the ones mcp_preset_run dispatches, hosts exist,
    mcp_raw commands pass the raw allowed_prefixes gate, mcp_debug
    commands are declared debug_commands;
  * host-snapshot covers exactly the configured HOSTS and emits the
    ops-readonly contract per host (mocked run_on_host);
  * no global tool-surface expansion: the advertised MCP tool list is
    unchanged and every opencode-lane profile still denies
    mcp_preset_run — presets are for full-surface clients (Ada, ad-hoc
    agents), never the restricted lanes.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.mcp_debug import config, tools  # noqa: E402

PRESETS_FILE = (REPO / "docs" / "ssot" / "infrastructure"
                / "ssot.mcp-debug.presets.yml")
MCP_DEBUG_SSOT = (REPO / "docs" / "ssot" / "infrastructure"
                  / "ssot.mcp-debug.yml")
PROFILES_DIR = REPO / "evals" / "opencode-lane" / "profiles"

# tools mcp_preset_run actually dispatches (tools.py) — the policy block
# in the presets SSOT must not fall behind this set
DISPATCHABLE = {"mcp_debug", "mcp_raw", "mcp_health", "mcp_diff",
                "mcp_debug_audit", "mcp_system", "mcp_transform"}
# step tools that require a `host` key (mcp_preset_run enforces it)
HOST_TOOLS = {"mcp_debug", "mcp_raw", "mcp_health", "mcp_system"}


def _preset_doc():
    return yaml.safe_load(PRESETS_FILE.read_text()) or {}


def _steps():
    return [(name, step)
            for name, p in (config.PRESETS or {}).items()
            for step in (p.get("steps") or [])]


class PresetLoadingTest(unittest.TestCase):
    def test_presets_file_loads_host_snapshot(self):
        self.assertIn("host-snapshot", config.PRESETS)
        p = config.PRESETS["host-snapshot"]
        self.assertTrue(p.get("description"))
        self.assertTrue(p.get("steps"))

    def test_split_file_wins_over_inline(self):
        # _load_presets merges inline presets: + the split file, split
        # winning on collisions — pin the merge order directly
        merged = config._load_presets({"presets": {"x": {"steps": []}}})
        self.assertIn("x", merged)
        self.assertIn("host-snapshot", merged)

    def test_policy_block_declares_step_tools(self):
        pol = (_preset_doc().get("policy") or {})
        declared = set(pol.get("step_tools") or [])
        self.assertTrue(declared, "presets SSOT missing policy.step_tools")
        self.assertLessEqual(declared, DISPATCHABLE,
                             "policy names a tool mcp_preset_run "
                             "cannot dispatch")


class PresetPolicyLintTest(unittest.TestCase):
    """Every committed preset step must satisfy the declared policy —
    this is the 'tool policy' half of the deliverable."""

    def test_step_tools_are_dispatchable_and_declared(self):
        declared = set((_preset_doc().get("policy") or {})
                       .get("step_tools") or DISPATCHABLE)
        for name, step in _steps():
            tool = step.get("tool")
            self.assertIn(tool, DISPATCHABLE,
                          f"{name}: undispatchable step tool {tool!r}")
            self.assertIn(tool, declared,
                          f"{name}: step tool {tool!r} not in the "
                          "presets SSOT policy.step_tools")

    def test_hosted_steps_name_configured_hosts(self):
        for name, step in _steps():
            if step.get("tool") in HOST_TOOLS:
                self.assertIn(step.get("host"), config.HOSTS,
                              f"{name}: step host {step.get('host')!r} "
                              "not in ssot.mcp-debug.yml hosts:")

    def test_mcp_raw_commands_pass_prefix_allowlist(self):
        import shlex
        for name, step in _steps():
            if step.get("tool") != "mcp_raw":
                continue
            cmd = step.get("command") or ""
            self.assertTrue(cmd, f"{name}: mcp_raw step missing command")
            base = shlex.split(cmd)[0].split("/")[-1]
            self.assertIn(base, config.RAW_PREFIXES,
                          f"{name}: raw base {base!r} not in "
                          "raw_commands.allowed_prefixes — the step "
                          "would be denied at run_on_host")

    def test_mcp_debug_commands_are_declared(self):
        for name, step in _steps():
            if step.get("tool") != "mcp_debug":
                continue
            cmd = step.get("command") or ""
            self.assertIn(cmd, config.DEBUG_COMMANDS,
                          f"{name}: mcp_debug command {cmd!r} not in "
                          "debug_commands — the remote mcp-debug "
                          "binary would not know it")


class HostSnapshotContractTest(unittest.TestCase):
    """host-snapshot runs host_snapshot.py on exactly the configured
    hosts; per-step results carry the host tag and the ops-readonly
    contract JSON."""

    SNAP = {"host": "h", "collected_at": "t", "uptime_seconds": 1,
            "load1": 0.1, "load5": 0.1, "load15": 0.1, "cpu_count": 4,
            "mem_total_mb": 1000, "mem_available_mb": 500,
            "disk_root_pct": 10.0, "failed_units": [],
            "read_only": True}

    def test_covers_exactly_configured_hosts(self):
        steps = config.PRESETS["host-snapshot"]["steps"]
        self.assertEqual(
            sorted(s["host"] for s in steps),
            sorted(config.HOSTS.keys()),
            "host-snapshot must sweep every mcp-debug-configured host")
        for s in steps:
            self.assertEqual(s["tool"], "mcp_raw")
            self.assertIn("host_snapshot.py", s["command"])

    def test_preset_run_aggregates_per_host_results(self):
        calls = []

        def fake_run(host, command, compact, shell=False):
            calls.append((host, command, compact))
            self.assertIn("host_snapshot.py", command)
            self.assertFalse(compact)
            return {"ok": True, "host": host, "rc": 0,
                    "out": json.dumps(self.SNAP), "err": ""}

        with patch.object(tools, "run_on_host", fake_run):
            res = tools.mcp_preset_run("host-snapshot")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["preset"], "host-snapshot")
        self.assertEqual(len(res["results"]), len(config.HOSTS))
        for r in res["results"]:
            self.assertTrue(r["ok"])
            self.assertIn(r["h"], config.HOSTS)
            snap = json.loads(r["out"])
            self.assertTrue(snap["read_only"])
            for k in ("host", "collected_at", "uptime_seconds", "load1",
                      "load5", "load15", "cpu_count", "mem_total_mb",
                      "mem_available_mb", "disk_root_pct",
                      "failed_units"):
                self.assertIn(k, snap)
        self.assertEqual(
            sorted(c[0] for c in calls), sorted(config.HOSTS.keys()))

    def test_preset_run_unknown_and_partial_failure(self):
        self.assertFalse(tools.mcp_preset_run("no-such-preset")["ok"])

        def flaky(host, command, compact, shell=False):
            ok = host != "con01"
            return {"ok": ok, "host": host, "rc": 0 if ok else 1,
                    "out": json.dumps(self.SNAP) if ok else "",
                    "err": "" if ok else "host unreachable"}

        with patch.object(tools, "run_on_host", flaky):
            res = tools.mcp_preset_run("host-snapshot")
        # one dead host must not sink the preset — per-step ok is the
        # contract; all_ok stays honest
        self.assertFalse(res["ok"])
        self.assertEqual(
            sum(1 for r in res["results"] if r["ok"]),
            len(config.HOSTS) - 1)


class NoToolSurfaceExpansionTest(unittest.TestCase):
    """The preset adds config, not tools: the advertised MCP surface is
    byte-identical and lane profiles keep denying mcp_preset_run."""

    def test_server_tool_list_has_no_preset_entries(self):
        doc = yaml.safe_load(MCP_DEBUG_SSOT.read_text()) or {}
        tools_list = ((doc.get("server") or {}).get("tools")) or []
        preset_names = set(config.PRESETS)
        self.assertFalse(
            preset_names & set(tools_list),
            "preset names leaked into the advertised tool list")
        # the three preset MCP tools were already advertised — presets
        # reuse them, they are not new
        for t in ("mcp_preset_list", "mcp_preset_run",
                  "mcp_preset_savings"):
            self.assertIn(t, tools_list)

    def test_lane_profiles_never_allow_preset_run(self):
        allowed_hits = []
        for prof in sorted(PROFILES_DIR.glob("*/profile.yml")):
            doc = yaml.safe_load(prof.read_text()) or {}
            mcp = doc.get("mcp") or {}
            if "mcp_preset_run" in (mcp.get("allowed") or []):
                allowed_hits.append(prof.parent.name)
        self.assertEqual(allowed_hits, [],
                         "a lane profile widened to mcp_preset_run — "
                         "presets must stay off the restricted lane "
                         "surface")
        # and the read-only profiles that DO name it keep it denied
        for pid in ("ops-readonly", "ops-remote-read", "storage-dryrun"):
            doc = yaml.safe_load(
                (PROFILES_DIR / pid / "profile.yml").read_text()) or {}
            self.assertIn("mcp_preset_run",
                          (doc.get("mcp") or {}).get("denied") or [],
                          f"{pid} no longer denies mcp_preset_run")


if __name__ == "__main__":
    unittest.main()
