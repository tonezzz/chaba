"""Tests for the x-litellm-tags / x-litellm-metadata header support added
to gemini_rest + litellm_chat (model-key-usage-control acceptance:
gateway-metered calls carry service/job/route metadata)."""

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gemini_rest = _load("gemini_rest", "scripts/ada/gemini_rest.py")
litellm_chat = _load("litellm_chat", "scripts/ada/litellm_chat.py")


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
CHAT_OK = {"choices": [{"message": {"content": "ok"}}]}


def _hdr(req, name):
    return req.get_header(name) or req.get_header(name.capitalize())


class GeminiRestTagsTest(unittest.TestCase):
    def test_gateway_call_sends_tag_headers(self):
        with patch.object(gemini_rest.urllib.request, "urlopen",
                          return_value=_Resp(GEMINI_OK)) as uo:
            gemini_rest.generate(
                "p", "gemini-3.5-flash-lite-free", key="vk",
                base_url_override="http://gw.test:4000", max_attempts=1,
                tags="service=x,job=y,route=z",
                litellm_metadata={"service": "x", "job": "y"})
        req = uo.call_args.args[0]
        self.assertEqual(_hdr(req, "X-litellm-tags"),
                         "service=x,job=y,route=z")
        self.assertEqual(json.loads(_hdr(req, "X-litellm-metadata")),
                         {"service": "x", "job": "y"})

    def test_direct_call_never_sends_tag_headers(self):
        # Direct Google: custom headers must be absent — the paid/direct
        # bypass gets no LiteLLM machinery.
        with patch.object(gemini_rest.urllib.request, "urlopen",
                          return_value=_Resp(GEMINI_OK)) as uo:
            gemini_rest.generate(
                "p", "gemini-3.5-flash-lite", key="gk",
                base_url_override="https://generativelanguage.googleapis.com",
                max_attempts=1, tags="service=x",
                litellm_metadata={"a": 1})
        req = uo.call_args.args[0]
        self.assertIsNone(_hdr(req, "X-litellm-tags"))
        self.assertIsNone(_hdr(req, "X-litellm-metadata"))

    def test_tags_accept_list(self):
        with patch.object(gemini_rest.urllib.request, "urlopen",
                          return_value=_Resp(GEMINI_OK)) as uo:
            gemini_rest.generate(
                "p", "m", key="vk",
                base_url_override="http://gw.test:4000", max_attempts=1,
                tags=["service=a", "job=b"])
        self.assertEqual(_hdr(uo.call_args.args[0], "X-litellm-tags"),
                         "service=a,job=b")

    def test_no_tags_no_headers(self):
        with patch.object(gemini_rest.urllib.request, "urlopen",
                          return_value=_Resp(GEMINI_OK)) as uo:
            gemini_rest.generate(
                "p", "m", key="vk",
                base_url_override="http://gw.test:4000", max_attempts=1)
        req = uo.call_args.args[0]
        self.assertIsNone(_hdr(req, "X-litellm-tags"))
        self.assertIsNone(_hdr(req, "X-litellm-metadata"))

    def test_generate_json_forwards_tags(self):
        payload = {"candidates": [{"content": {
            "parts": [{"text": '{"a": 1}'}]}}]}
        with patch.object(gemini_rest.urllib.request, "urlopen",
                          return_value=_Resp(payload)) as uo:
            out = gemini_rest.generate_json(
                "p", "m", key="vk",
                base_url_override="http://gw.test:4000",
                tags="service=x")
        self.assertEqual(out, {"a": 1})
        self.assertEqual(_hdr(uo.call_args.args[0], "X-litellm-tags"),
                         "service=x")


class LitellmChatTagsTest(unittest.TestCase):
    def test_chat_sends_tag_headers(self):
        with patch.object(litellm_chat.urllib.request, "urlopen",
                          return_value=_Resp(CHAT_OK)) as uo:
            litellm_chat.chat(
                "p", url="http://gw.test:4000/v1", key="vk",
                tags="service=news-digest,job=wp-news-digest",
                litellm_metadata={"route": "en_synth"})
        req = uo.call_args.args[0]
        self.assertEqual(_hdr(req, "X-litellm-tags"),
                         "service=news-digest,job=wp-news-digest")
        self.assertEqual(json.loads(_hdr(req, "X-litellm-metadata")),
                         {"route": "en_synth"})

    def test_chat_no_tags_no_headers(self):
        with patch.object(litellm_chat.urllib.request, "urlopen",
                          return_value=_Resp(CHAT_OK)) as uo:
            litellm_chat.chat("p", url="http://gw.test:4000/v1", key="vk")
        req = uo.call_args.args[0]
        self.assertIsNone(_hdr(req, "X-litellm-tags"))
        self.assertIsNone(_hdr(req, "X-litellm-metadata"))


if __name__ == "__main__":
    unittest.main()
