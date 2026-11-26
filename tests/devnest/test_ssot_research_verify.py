"""Unit tests for the ssot-research held-out verifier's citation
quote-verification (card ssot-research-verifier-semantic, KNB-1029
evidence): every citation note must carry a quoted string that really
appears in the cited file — path existence alone let a fabricated
qwen3:8b answer pass on 2026-10-30.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERIFY = (REPO / "evals/opencode-lane/profiles/ssot-research"
          / "fixture/verify.py")

TASK = ("What does the fleet declare about kk-mac — its host entry, "
        "its ollama capability, and the LiteLLM routes that reach it?")

# Verbatim strings confirmed present in the cited files.
AGENTS_QUOTE = "never edit the live checkout"
AUDIT_QUOTE = "kkmac-ollama-tunnel.service"


def _load_verify():
    spec = importlib.util.spec_from_file_location(
        "ssot_research_verify", VERIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _artifact(citations):
    return {
        "question": TASK,
        "answer": "kk-mac's ollama is reached via an ssh tunnel "
                  "declared in the fleet audit SSOT.",
        "citations": citations,
        "sources_consulted": ["AGENTS.md",
                              "docs/ssot/infrastructure/"
                              "ssot.audit.hosts.yml"],
        "read_only": True,
    }


GOOD_CITATIONS = [
    {"path": "AGENTS.md",
     "note": f"checkout rule says \"{AGENTS_QUOTE}\""},
    {"path": "docs/ssot/infrastructure/ssot.audit.hosts.yml",
     "note": f"tunnel unit \"{AUDIT_QUOTE}\" fronts kk-mac ollama"},
]

# The KNB-1029 artifact verbatim (evals/opencode-lane/reports/
# 2026-11-07-session-audit.json, ses_e72e4865dffeSHpW6C3zDQtnTG):
# real paths, fabricated claims (/etc/hosts + MCP tools; truth is
# ssot.audit.hosts.yml + stacks/idc03/litellm/config.yaml), notes
# with no quotes at all.
KNB1029_CITATIONS = [
    {"path": "AGENTS.md",
     "note": "References ollama-qwen38b-kkmac model and host entry "
             "configuration"},
    {"path": "docs/ssot/infrastructure/ssot.mcp.yml",
     "note": "Contains LiteLLM route definitions for kk-mac"},
]


class SsotResearchVerifyTest(unittest.TestCase):
    def setUp(self):
        self.v = _load_verify()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rd = Path(self.tmp.name)
        (self.rd / "manifest.json").write_text(json.dumps(
            {"envelope": {"task": TASK}}))

    def run_verify(self, citations):
        (self.rd / "artifact.out").write_text(
            json.dumps(_artifact(citations)))
        return self.v.verify(self.rd)

    def test_knb1029_fabricated_artifact_now_fails(self):
        res = self.run_verify(KNB1029_CITATIONS)
        self.assertEqual(res["verdict"], "fail", res)
        self.assertFalse(
            res["checks"]["every citation quote verified"])
        self.assertEqual(
            {u["reason"] for u in
             res["checks"]["unverified citations"]},
            {"no quote"})

    def test_real_quotes_pass(self):
        res = self.run_verify(GOOD_CITATIONS)
        self.assertEqual(res["verdict"], "pass", res)
        self.assertTrue(
            res["checks"]["every citation quote verified"])

    def test_quote_not_in_file_fails(self):
        cits = [dict(GOOD_CITATIONS[0]),
                {"path": "docs/ssot/infrastructure/ssot.audit.hosts.yml",
                 "note": "claims \"this string is not in the file\""}]
        res = self.run_verify(cits)
        self.assertEqual(res["verdict"], "fail")
        self.assertEqual(
            res["checks"]["unverified citations"],
            [{"path": "docs/ssot/infrastructure/ssot.audit.hosts.yml",
              "reason": "quote not in file"}])

    def test_short_quote_rejected(self):
        # <8 chars is not a verifiable quote — fails closed
        cits = [dict(GOOD_CITATIONS[0]),
                {"path": "docs/ssot/infrastructure/ssot.audit.hosts.yml",
                 "note": "mentions \"kk-mac\" briefly"}]
        res = self.run_verify(cits)
        self.assertEqual(res["verdict"], "fail")

    def test_whitespace_normalized_match(self):
        # a quote spanning a line-wrap in the source still verifies
        cits = [dict(GOOD_CITATIONS[0]),
                {"path": "docs/ssot/infrastructure/ssot.audit.hosts.yml",
                 "note": "tunnel note includes \"ssh -N -L "
                         "127.0.0.1:11445:127.0.0.1:11434\""}]
        res = self.run_verify(cits)
        self.assertEqual(res["verdict"], "pass", res)

    def test_missing_path_still_fails_without_quote_noise(self):
        cits = GOOD_CITATIONS + [
            {"path": "docs/ssot/no-such-file.yml",
             "note": "\"does not matter\""}]
        res = self.run_verify(cits)
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["every cited path exists"])


if __name__ == "__main__":
    unittest.main()
