"""Contract tests for the MCP fleet scope / status / finding-ID standard (OPS-0025)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "mcp_inventory", REPO / "scripts" / "mcp-inventory.py")
mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp)


FLEET = {
    "scope_model": {"default": "agent-lanes",
                    "agent_lane_hosts": ["tony_omen", "tony_dell"]},
    "expected_statuses": ["operational"],
    "finding_states": ["open", "carded", "suppressed"],
    "finding_triage": {},
}


def test_scope_agent_lanes_and_named_hosts():
    assert mcp.in_scope(FLEET, "github", {"scope": "agent-lanes"}, "tony_omen")
    assert not mcp.in_scope(FLEET, "github", {"scope": "agent-lanes"}, "idc02")
    assert mcp.in_scope(FLEET, "x", {"scope": "fleet"}, "idc02")
    assert mcp.in_scope(FLEET, "x", {"scope": ["mn01"]}, "mn01")
    assert not mcp.in_scope(FLEET, "x", {"scope": ["mn01"]}, "tony_dell")


def test_per_host_narrows_scope():
    spec = {"scope": "agent-lanes", "per_host": {"tony_dell": {}}}
    assert mcp.in_scope(FLEET, "x", spec, "tony_dell")
    assert not mcp.in_scope(FLEET, "x", spec, "tony_omen")


@pytest.mark.parametrize("spec", [{}, {"scope": "everywhere"}])
def test_bad_scope_fails_loud(spec):
    with pytest.raises(ValueError, match="scope"):
        mcp.in_scope(FLEET, "x", spec, "tony_omen")


def test_finding_id_is_stable_across_server_sets():
    assert mcp.finding_id("tony_omen", "missing-active") == \
        mcp.finding_id("tony_omen", "missing-active")
    assert mcp.finding_id("tony_omen", "missing-active") != \
        mcp.finding_id("tony_dell", "missing-active")


def test_triage_defaults_and_human_states():
    fid = mcp.finding_id("tony_omen", "missing-active")
    fleet = dict(FLEET)
    fleet["finding_triage"] = {
        fid: {"state": "carded", "card": "OPS-0025", "by": "tony"}}
    t = mcp.triage_for(fleet, fid, "2026-11-20")
    assert t["state"] == "carded" and t["card"] == "OPS-0025"
    assert mcp.triage_for(FLEET, fid, "2026-11-20")["state"] == "open"


def test_suppression_needs_reason_and_expires():
    fid = mcp.finding_id("idc02", "undeclared-configured")
    fleet = dict(FLEET)
    fleet["finding_triage"] = {fid: {"state": "suppressed"}}
    with pytest.raises(ValueError, match="reason"):
        mcp.triage_for(fleet, fid, "2026-11-20")
    fleet["finding_triage"][fid]["reason"] = "job host has no agent lane"
    fleet["finding_triage"][fid]["until"] = "2026-11-19"
    expired = mcp.triage_for(fleet, fid, "2026-11-20")
    assert expired["state"] == "open" and expired["expired"]
    fleet["finding_triage"][fid]["until"] = "2026-11-30"
    assert mcp.triage_for(fleet, fid, "2026-11-20")["state"] == "suppressed"


def test_no_config_is_in_report_contract():
    from lib.report import STATUSES
    assert "no-config" in STATUSES
