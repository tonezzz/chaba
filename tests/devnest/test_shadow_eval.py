"""Tests for the DevNest shadow-eval harness + rainy-day ladder
(scripts/devnest/shadow_eval.py). Uses synthetic probe dicts — no network.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/devnest/shadow_eval.py"

spec = importlib.util.spec_from_file_location("shadow_eval", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["shadow_eval"] = mod
spec.loader.exec_module(mod)


def mkprobe(**net):
    """Synthetic probe with all tools present; net flags overridable."""
    base = {"litellm": True, "litellm_authed": True, "ollama_idc02": True,
            "ollama_idc03": True, "ollama_local": True, "tailnet": True,
            "wan": True, "devin_cloud": True}
    base.update(net)
    return {"host": "test", "at": "x", "simulated": None,
            "tools": {"opencode": True, "devin": True, "ollama": True,
                      "git": True, "python3": True},
            "net": base,
            "secrets": {"litellm_keys_env": True,
                        "litellm_chaba_env": False},
            "models": {}}


OFFLINE = mkprobe(litellm=False, litellm_authed=False, ollama_idc02=False,
                  ollama_idc03=False, tailnet=False, wan=False,
                  devin_cloud=False)
AIRGAP = mkprobe(**{k: False for k in mkprobe()["net"]})


class FallbackSelection(unittest.TestCase):
    """The rainy-day ladder must pick the cheapest sufficient rung and
    never select a rung whose requirements are unmet."""

    def test_full_connectivity_llm_task_uses_l1_local(self):
        r = mod.route("summarize this text", mkprobe(), needs_llm=True,
                      prompt_chars=100)
        self.assertEqual(r["rung"], "L1")

    def test_l1_skipped_for_large_prompt(self):
        r = mod.route("refactor everything", mkprobe(), needs_llm=True,
                      prompt_chars=mod.L1_MAX_PROMPT_CHARS + 1)
        self.assertEqual(r["rung"], "L2")

    def test_no_local_ollama_falls_to_l2(self):
        r = mod.route("summarize", mkprobe(ollama_local=False),
                      needs_llm=True, prompt_chars=50)
        self.assertEqual(r["rung"], "L2")

    def test_tailnet_down_falls_to_l3_wan(self):
        r = mod.route("summarize", mkprobe(
            ollama_local=False, litellm=False, litellm_authed=False),
            needs_llm=True, prompt_chars=50)
        self.assertEqual(r["rung"], "L3")

    def test_wan_only_no_opencode_tool_goes_devin_or_manual(self):
        p = mkprobe(ollama_local=False, litellm=False,
                    litellm_authed=False, ollama_idc02=False,
                    ollama_idc03=False)
        p["tools"]["opencode"] = False
        r = mod.route("summarize", p, needs_llm=True, prompt_chars=50)
        self.assertEqual(r["rung"], "L4")

    def test_offline_with_loopback_ollama_uses_l1(self):
        # offline = no tailnet/WAN, but loopback ollama is still legal
        r = mod.route("summarize this", OFFLINE, needs_llm=True,
                      prompt_chars=50)
        self.assertEqual(r["rung"], "L1")

    def test_offline_no_ollama_goes_manual(self):
        p = dict(OFFLINE)
        p["net"] = dict(OFFLINE["net"], ollama_local=False)
        r = mod.route("summarize this", p, needs_llm=True,
                      prompt_chars=50)
        self.assertEqual(r["rung"], "MANUAL")

    def test_airgap_llm_task_goes_manual(self):
        r = mod.route("summarize this", AIRGAP, needs_llm=True,
                      prompt_chars=50)
        self.assertEqual(r["rung"], "MANUAL")

    def test_failed_rung_escalates(self):
        r = mod.route("summarize", mkprobe(), needs_llm=True,
                      prompt_chars=50, failed=["L1"])
        self.assertEqual(r["rung"], "L2")

    def test_manual_keyword_routes_manual(self):
        r = mod.route("buy a replacement nvme for omen", mkprobe())
        self.assertEqual(r["rung"], "MANUAL")

    def test_offline_fixture_routes_l0(self):
        for fid in mod.list_fixtures():
            r = mod.route_fixture(fid, OFFLINE)
            self.assertEqual(r["rung"], "L0",
                             f"{fid} must still be deterministic-offline")
            self.assertFalse(any(r2.get("net") for r2 in mod.RUNGS
                                 if r2["id"] == "L0"))

    def test_fixture_with_failed_l0_climbs_ladder(self):
        r = mod.route_fixture("host-health", mkprobe(), failed=["L0"])
        self.assertIn(r["rung"], ("L1", "L2", "L3", "L4"))


class CapabilityMatrix(unittest.TestCase):
    def statuses(self, p, **kw):
        return {e["rung"]: e["status"]
                for e in mod.evaluate_rungs(p, **kw)}

    def test_all_up(self):
        s = self.statuses(mkprobe())
        self.assertEqual(s["L0"], "PASS")
        self.assertIn(s["L1"], ("PASS", "DEGRADED"))
        self.assertIn(s["L4"], ("PASS", "DEGRADED"))
        self.assertEqual(s["MANUAL"], "PASS")

    def test_airgap_blocks_all_llm_rungs(self):
        s = self.statuses(AIRGAP, needs_llm=True)
        for rung in ("L0", "L1", "L2", "L3", "L4"):
            self.assertEqual(s[rung], "BLOCKED", f"{rung} must be BLOCKED "
                             "in an air gap for llm-needing work")
        self.assertEqual(s["MANUAL"], "PASS")

    def test_needs_llm_blocks_l0(self):
        s = self.statuses(mkprobe(), needs_llm=True)
        self.assertEqual(s["L0"], "BLOCKED")

    def test_missing_opencode_blocks_l1_l2_l3(self):
        p = mkprobe()
        p["tools"]["opencode"] = False
        s = self.statuses(p, needs_llm=True)
        for rung in ("L1", "L2", "L3"):
            self.assertEqual(s[rung], "BLOCKED")
        self.assertEqual(s["L4"], "PASS")


class SecretGuard(unittest.TestCase):
    def test_load_arm_env_refuses_offline(self):
        import os
        os.environ["SHADOW_OFFLINE"] = "1"
        try:
            with self.assertRaises(RuntimeError):
                mod.load_arm_env("L2", "litellm/x")
        finally:
            del os.environ["SHADOW_OFFLINE"]

    def test_l0_never_needs_secrets(self):
        l0 = next(r for r in mod.RUNGS if r["id"] == "L0")
        self.assertFalse(l0["secrets"])
        self.assertFalse(l0["net"])


class FixtureIntegrity(unittest.TestCase):
    def test_five_fixtures_present(self):
        self.assertEqual(sorted(mod.list_fixtures()),
                         ["backup-freshness", "host-health", "mcp-safety",
                          "storage-dryrun", "worktree-safety"])

    def test_each_fixture_has_contract_files(self):
        for fid in mod.list_fixtures():
            d = mod.fixture_dir(fid)
            for f in ("task.yaml", "prompt.md", "l0.py", "verify.py"):
                self.assertTrue((d / f).is_file(), f"{fid}/{f} missing")
            meta = mod.fixture_meta(fid)
            self.assertEqual(str(meta.get("class")), "read_only")
            self.assertEqual(str(meta.get("needs_llm")).lower(), "false")


if __name__ == "__main__":
    unittest.main()
