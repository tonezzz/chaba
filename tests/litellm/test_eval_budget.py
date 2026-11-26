"""Tests for scripts/litellm/eval-budget.py — the eval-judge lane client
(card gemini-eval-judge-lane): daily cap, JSONL ledger, service=eval
tagging, and the parked-without-provider-request guarantee."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "eval_budget", REPO / "scripts/litellm/eval-budget.py")
eb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eb)

ENV_VARS = ("LITELLM_URL", "LITELLM_KEY_EVAL_JUDGE",
            "EVAL_JUDGE_MODEL", "EVAL_JUDGE_DAILY_MAX",
            "EVAL_JUDGE_STATE_DIR", "BOARD_API")


class _Resp:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def _payload(text="answer", **usage):
    u = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    u.update(usage)
    return {"choices": [{"message": {"content": text}}],
            "usage": u, "model": "gemini/gemini-3.5-flash-lite"}


class EvalBudgetCase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_VARS}
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["EVAL_JUDGE_STATE_DIR"] = self._tmp.name
        os.environ["EVAL_JUDGE_DAILY_MAX"] = "10000"
        os.environ["LITELLM_KEY_EVAL_JUDGE"] = "sk-test-eval-judge"
        os.environ["LITELLM_URL"] = "http://127.0.0.1:9"
        # isolate from any real litellm-keys.env on the host
        self._keys = eb.KEYS_ENV
        eb.KEYS_ENV = Path(self._tmp.name) / "no-such-keys.env"
        self.addCleanup(self._restore)

    def _restore(self):
        eb.KEYS_ENV = self._keys
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_ok_call_ledgers_row_and_tags(self):
        seen = []

        def fake(req, timeout=None):
            seen.append(req)
            return _Resp(_payload("escalate"),
                         {"x-litellm-attempted-fallbacks": "0"})

        with mock.patch.object(eb, "_urlopen", fake):
            r = eb.chat([{"role": "user", "content": "q"}], task="t1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["verdict"], "escalate")
        self.assertEqual(r["fallback_hops"], 0)
        self.assertEqual(r["tokens"]["total"], 12)
        hdrs = {k.lower(): v for k, v in seen[0].header_items()}
        self.assertIn("service=eval", hdrs["x-litellm-tags"])
        self.assertIn("job=t1", hdrs["x-litellm-tags"])
        rows = eb._rows_for(eb.ledger_file())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        for k in ("ts", "task", "tokens", "spend_usd", "verdict"):
            self.assertIn(k, row)
        self.assertTrue(row["provider_call"])
        self.assertEqual(eb.used_today(), 1)

    def test_daily_cap_parks_without_provider_request(self):
        os.environ["EVAL_JUDGE_DAILY_MAX"] = "2"
        posts = []
        with mock.patch.object(
                eb, "_urlopen",
                lambda req, timeout=None: _Resp(_payload("answer"))):
            r1 = eb.chat([{"role": "user", "content": "a"}], task="cap")
            r2 = eb.chat([{"role": "user", "content": "b"}], task="cap")
            self.assertTrue(r1["ok"] and r2["ok"])
            r3 = eb.chat([{"role": "user", "content": "c"}], task="cap",
                         park_card="some-card",
                         post_comment=lambda cid, text: posts.append(
                             (cid, text)) or "ok")
        self.assertTrue(r3.get("parked"))
        self.assertEqual(r3["status"], "parked")
        self.assertIn("EVAL_JUDGE_DAILY_MAX", r3["detail"])
        self.assertEqual(posts and posts[0][0], "some-card")
        # exactly two provider calls were made; third never left the host
        self.assertEqual(eb.used_today(), 2)
        statuses = [r["status"] for r in eb._rows_for(eb.ledger_file())]
        self.assertEqual(statuses, ["ok", "ok", "parked"])

    def test_unconfigured_makes_no_provider_request(self):
        os.environ.pop("LITELLM_KEY_EVAL_JUDGE")
        with mock.patch.object(eb, "_urlopen",
                               side_effect=AssertionError("no http")):
            r = eb.chat([{"role": "user", "content": "q"}], task="nocfg")
        self.assertEqual(r["status"], "unconfigured")
        self.assertFalse(r["provider_call"])

    def test_provider_error_is_ledgered_not_retried(self):
        import urllib.error
        err = urllib.error.HTTPError(
            "http://x", 429, "rate limited", {}, None)
        with mock.patch.object(eb, "_urlopen", side_effect=err):
            r = eb.chat([{"role": "user", "content": "q"}], task="err")
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], "provider_error")
        self.assertEqual(r["http"], 429)
        self.assertTrue(r["provider_call"])
        self.assertEqual(eb.used_today(), 1)  # attempt counts toward cap

    def test_no_generic_key_fallback(self):
        """LITELLM_KEY (generic) must NOT serve this lane — budget
        isolation is the point of the dedicated virtual key."""
        os.environ.pop("LITELLM_KEY_EVAL_JUDGE")
        os.environ["LITELLM_KEY"] = "sk-generic-must-not-be-used"
        with mock.patch.object(eb, "_urlopen",
                               side_effect=AssertionError("no http")):
            r = eb.chat([{"role": "user", "content": "q"}], task="iso")
        self.assertEqual(r["status"], "unconfigured")


if __name__ == "__main__":
    unittest.main()
