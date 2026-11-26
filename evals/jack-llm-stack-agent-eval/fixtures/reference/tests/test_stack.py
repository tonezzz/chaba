#!/usr/bin/env python3
"""Deterministic offline tests for the disposable Jack LLM stack."""
import json
import os
import re
import stat
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestArtifacts(unittest.TestCase):
    def test_required_files_exist(self):
        for rel in [
            "docker-compose.yml", "litellm/config.yaml",
            "opencode/opencode.json", "env.example",
            "healthcheck.sh", "rollback.sh", "verify.sh",
            "RUNBOOK.md", "mock/mock_stack.py",
        ]:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), rel)

    def test_scripts_executable(self):
        for rel in ["healthcheck.sh", "rollback.sh", "verify.sh"]:
            mode = os.stat(os.path.join(ROOT, rel)).st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"{rel} not executable")

    def test_opencode_json_valid_and_wired(self):
        cfg = json.loads(read("opencode/opencode.json"))
        prov = cfg["provider"]
        self.assertTrue(prov, "no provider block")
        p = next(iter(prov.values()))
        opts = p.get("options", {})
        self.assertIn("baseURL", opts)
        self.assertIn("/v1", opts["baseURL"])
        self.assertTrue(p.get("models"), "provider has no models")

    def test_litellm_routes_local_only(self):
        cfg = read("litellm/config.yaml")
        self.assertIn("model_list", cfg)
        self.assertIn("ollama_chat/", cfg)
        # no paid/external upstreams
        for bad in ("openrouter", "gemini/", "anthropic", "api.openai.com"):
            self.assertNotIn(bad, cfg.lower())

    def test_env_example_placeholders_only(self):
        txt = read("env.example")
        for line in txt.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            if re.search(r"(?i)(key|token|secret|pass)", k):
                self.assertTrue(
                    re.search(r"(?i)(change_me|placeholder|\$\{|<|os\.environ)", v),
                    f"{k} has non-placeholder value: {v!r}")

    def test_compose_resource_limits(self):
        cfg = read("docker-compose.yml")
        self.assertRegex(cfg, r"(?i)memory:\s*\d")
        self.assertRegex(cfg, r"(?i)cpus:\s*\"?[\d.]")
        self.assertIn("OLLAMA_MAX_LOADED_MODELS", cfg)
        # loopback-only publishes
        self.assertNotIn("0.0.0.0:", cfg.split("ports:")[1] if "ports:" in cfg else "")

    def test_model_choice_is_small(self):
        cfg = read("litellm/config.yaml") + read("env.example") + read("RUNBOOK.md")
        self.assertRegex(
            cfg,
            r"(?i)(qwen2\.5:3b|qwen2\.5coder:1\.5b|llama3\.2:3b|"
            r"qwen3:4b|gemma3:1b|phi3\.5)")

    def test_runbook_sections(self):
        txt = read("RUNBOOK.md").lower()
        for sec in ("deploy", "verify", "rollback", "health", "model"):
            self.assertIn(sec, txt, f"runbook missing '{sec}'")


if __name__ == "__main__":
    unittest.main()
