"""Unit tests for the doc-draft held-out verifier's card-declared
verify contract (card doc-draft-verifier-semantic-gap, OPS-1014
evidence): action.verify_contains / verify_sections sentinels,
action.verify_regex patterns, and action.verify_min_terms keyword
coverage — all fetched live from board-api and patched here.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERIFY = (REPO / "evals/opencode-lane/profiles/doc-draft"
          / "fixture/verify.py")

# The OPS-1014 artifact: qwen2.5:32b emitted a code-summary of
# runner-agent.py instead of the specced model-notes doc. It names the
# same files/functions a sentinel list would pick — mechanical checks
# passed, semantics did not.
CODE_SUMMARY = """# runner-agent.py summary

### Task Dispatch and Claiming

The runner checks `is_claimable(card)` in scripts/board/runner-agent.py:
action.status must be queued, executor pins honored, host pins checked.

### Resource Management

systemd-run properties apply CPUQuota, MemoryMax, Nice and IOWeight to
each devin-task-* unit; RuntimeMaxSec bounds wall clock when
action.timeout_s is declared.

### OpenCode lane closeout

finish_opencode_lane lands the artifact, runs the held-out verifier
(verify_contains sentinels from the card), audits events.jsonl for
denials, and only then allows the merge gate to proceed.
"""

MODEL_NOTES = """# docs/kb/opencode-lane-model-notes.md

Which LiteLLM models work on the OpenCode dispatch lane on idc02.

## Verified working

- or-gemini-3.5-flash — full pass, health JSON artifact verified.
- ollama-qwen38b-kkmac — doc-draft default, grounded KB doc merged.

## Contract

ops-readonly emits JSON artifacts; doc-draft emits markdown. The runner
writes artifacts — agents emit them as their final message only.
RAILS_OPENCODE in scripts/board/runner-agent.py is the prompt block.
"""


def _load_verify():
    spec = importlib.util.spec_from_file_location(
        "doc_draft_verify", VERIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DocDraftVerifyTest(unittest.TestCase):
    def setUp(self):
        self.v = _load_verify()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rd = Path(self.tmp.name)
        (self.rd / "manifest.json").write_text(json.dumps(
            {"envelope": {"card": "c1",
                          "artifact": {"path": "docs/kb/x.md"}}}))

    def artifact(self, text):
        (self.rd / "artifact.out").write_text(text)
        return self.rd

    def contract(self, **kw):
        self.v._card_contract = lambda cid: (kw, "")

    def no_contract(self):
        self.v._card_contract = lambda cid: ({}, "")

    def fetch_fails(self):
        self.v._card_contract = lambda cid: (None, "boom")

    def test_no_contract_passes_on_structure(self):
        self.no_contract()
        res = self.v.verify(self.artifact(MODEL_NOTES))
        self.assertEqual(res["verdict"], "pass", res)
        self.assertTrue(res["checks"]["verify contract declared"])

    def test_fetch_failure_fails_closed(self):
        self.fetch_fails()
        res = self.v.verify(self.artifact(MODEL_NOTES))
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["contract fetch"])

    def test_sentinels_present_and_missing(self):
        self.contract(verify_contains=["runner-agent.py"])
        self.assertEqual(
            self.v.verify(self.artifact(CODE_SUMMARY))["verdict"], "pass")
        self.contract(verify_contains=["runner-agent.py",
                                       "no-such-string"])
        res = self.v.verify(self.artifact(CODE_SUMMARY))
        self.assertEqual(res["verdict"], "fail")
        self.assertEqual(res["checks"]["missing sentinels"],
                         ["no-such-string"])

    def test_verify_sections_alias_still_works(self):
        self.contract(verify_sections=["ollama-qwen38b-kkmac"])
        self.assertEqual(
            self.v.verify(self.artifact(MODEL_NOTES))["verdict"], "pass")

    def test_verify_regex(self):
        self.contract(verify_regex=[r"## Verified working",
                                    r"ops-readonly.*JSON"])
        self.assertEqual(
            self.v.verify(self.artifact(MODEL_NOTES))["verdict"], "pass")
        self.contract(verify_regex=[r"## Verified working",
                                    r"## Nonexistent section"])
        res = self.v.verify(self.artifact(MODEL_NOTES))
        self.assertEqual(res["verdict"], "fail")
        self.assertEqual(res["checks"]["regex misses"],
                         [r"## Nonexistent section"])

    def test_verify_regex_uncompilable_fails_closed(self):
        self.contract(verify_regex=["([unclosed"])
        res = self.v.verify(self.artifact(MODEL_NOTES))
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["verify_regex matched"])
        self.assertEqual(res["checks"]["regex uncompilable"],
                         ["([unclosed"])

    def test_verify_min_terms_dict_and_bare_list(self):
        self.contract(verify_min_terms={
            "terms": ["litellm", "markdown", "final message"],
            "at_least": 2})
        self.assertEqual(
            self.v.verify(self.artifact(MODEL_NOTES))["verdict"], "pass")
        # bare list = all terms required
        self.contract(verify_min_terms=["litellm", "nonexistent-term"])
        res = self.v.verify(self.artifact(MODEL_NOTES))
        self.assertEqual(res["verdict"], "fail")
        self.assertEqual(res["checks"]["terms missed"],
                         ["nonexistent-term"])

    def test_verify_min_terms_unsatisfiable_fails(self):
        self.contract(verify_min_terms={
            "terms": ["litellm"], "at_least": 5})
        res = self.v.verify(self.artifact(MODEL_NOTES))
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["verify_min_terms coverage"])

    def test_verify_min_terms_bad_spec_fails_closed(self):
        self.contract(verify_min_terms=42)
        res = self.v.verify(self.artifact(MODEL_NOTES))
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["verify_min_terms coverage"])

    def test_ops1014_replay_offspec_doc_now_catchable(self):
        """The OPS-1014 miss: code names satisfy sentinels, but the
        specced deliverable's terms/shape do not. With a real contract
        declared, the same artifact must fail."""
        # what actually happened: no contract -> structural pass
        self.no_contract()
        res = self.v.verify(self.artifact(CODE_SUMMARY))
        self.assertEqual(res["verdict"], "pass", res)
        # what a competent spec would have declared
        self.contract(
            verify_contains=["runner-agent.py"],   # appears in BOTH
            verify_regex=[r"model notes|LiteLLM models"],
            verify_min_terms={"terms": ["LiteLLM", "ops-readonly",
                                        "doc-draft", "markdown"],
                              "at_least": 3})
        res = self.v.verify(self.artifact(CODE_SUMMARY))
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["verify_regex matched"])
        self.assertFalse(res["checks"]["verify_min_terms coverage"])
        # and the correct deliverable passes the same contract
        self.assertEqual(
            self.v.verify(self.artifact(MODEL_NOTES))["verdict"],
            "pass")


if __name__ == "__main__":
    unittest.main()
