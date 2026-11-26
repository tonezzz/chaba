"""Provider routing for scripts/ops/backlog-spec-enrich.py (ops-1037 /
OPS-1316): ENRICH_PROVIDER=litellm rides the OpenAI-compatible gateway
via litellm_chat.chat_json with x-litellm attribution; gemini_rest is
the fallback (explicit provider=gemini, or automatic on a failed litellm
reply for gemini-* models only)."""

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ops/backlog-spec-enrich.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "backlog_spec_enrich", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bse = _load()

GOOD = {"decision": "spec", "spec": "do the thing"}


class EnrichProviderTest(unittest.TestCase):
    def _run(self, provider, model, chat_ret, key="gkey",
             gen_ret=GOOD):
        with mock.patch.object(bse, "PROVIDER", provider), \
             mock.patch.object(bse, "MODEL", model), \
             mock.patch.object(bse.litellm_chat, "chat_json",
                               return_value=chat_ret) as cj, \
             mock.patch.object(bse.gemini_rest, "generate_json",
                               return_value=gen_ret) as gj:
            out = bse._enrich_json("prompt", "card-x", key)
        return out, cj, gj

    def test_litellm_success_never_touches_gemini(self):
        out, cj, gj = self._run("litellm", "gemini-3.5-flash-lite", GOOD)
        self.assertEqual(out, GOOD)
        gj.assert_not_called()
        kw = cj.call_args.kwargs
        self.assertEqual(kw["model"], "gemini-3.5-flash-lite")
        self.assertIn("backlog-spec-enrich", kw["tags"])
        self.assertEqual(kw["litellm_metadata"]["card"], "card-x")
        self.assertEqual(kw["litellm_metadata"]["route"], "spec_draft")

    def test_litellm_any_registered_route(self):
        # free local lane — no gemini fallback semantics needed
        out, cj, gj = self._run("litellm", "ollama-qwen38b-kkmac", GOOD)
        self.assertEqual(out, GOOD)
        self.assertEqual(cj.call_args.kwargs["model"],
                         "ollama-qwen38b-kkmac")
        gj.assert_not_called()

    def test_litellm_failure_falls_back_for_gemini_model(self):
        out, cj, gj = self._run("litellm", "gemini-3.5-flash-lite", None)
        self.assertEqual(out, GOOD)
        gj.assert_called_once()
        self.assertEqual(gj.call_args.args[1], "gemini-3.5-flash-lite")

    def test_litellm_failure_no_fallback_for_local_model(self):
        out, cj, gj = self._run("litellm", "ollama-qwen38b-kkmac", None)
        self.assertIsNone(out)
        gj.assert_not_called()

    def test_litellm_failure_no_key_no_fallback(self):
        out, cj, gj = self._run("litellm", "gemini-3.5-flash-lite", None,
                                key=None)
        self.assertIsNone(out)
        gj.assert_not_called()

    def test_provider_gemini_skips_gateway(self):
        out, cj, gj = self._run("gemini", "gemini-3.5-flash-lite", GOOD)
        self.assertEqual(out, GOOD)
        cj.assert_not_called()
        gj.assert_called_once()

    def test_provider_gemini_still_works_without_key(self):
        # generate_json itself handles the missing-key print; the wrapper
        # must not pre-empt it differently than the legacy path did.
        out, cj, gj = self._run("gemini", "gemini-3.5-flash-lite", None,
                                key=None, gen_ret=None)
        self.assertIsNone(out)
        gj.assert_not_called()  # no key -> early None, no call


if __name__ == "__main__":
    unittest.main()
