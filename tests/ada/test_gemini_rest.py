"""Tests for the shared Gemini REST helper's endpoint override."""

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "gemini_rest", REPO / "scripts/ada/gemini_rest.py")
gemini_rest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gemini_rest)


class GeminiRestTest(unittest.TestCase):
    def test_endpoint_override_adds_v1beta(self):
        self.assertEqual(
            gemini_rest.endpoint(
                "gemini-3.5-flash-lite-free",
                "http://gateway.test:4000"),
            "http://gateway.test:4000/v1beta/models/"
            "gemini-3.5-flash-lite-free:generateContent")

    def test_endpoint_override_preserves_v1beta(self):
        self.assertEqual(
            gemini_rest.endpoint(
                "gemini-3.5-flash-lite-free",
                "http://gateway.test:4000/v1beta/"),
            "http://gateway.test:4000/v1beta/models/"
            "gemini-3.5-flash-lite-free:generateContent")

    def test_generate_uses_gateway_override_and_virtual_key(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({
                    "candidates": [{
                        "content": {"parts": [{"text": "<p>Thai</p>"}]}
                    }]
                }).encode()

        with patch.object(gemini_rest.urllib.request, "urlopen",
                          return_value=Response()) as urlopen:
            text = gemini_rest.generate(
                "translate", "gemini-3.5-flash-lite-free",
                key="virtual-key", base_url_override="http://gateway.test:4000",
                max_attempts=1)

        self.assertEqual(text, "<p>Thai</p>")
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://gateway.test:4000/v1beta/models/"
            "gemini-3.5-flash-lite-free:generateContent")
        self.assertEqual(request.get_header("X-goog-api-key"), "virtual-key")


if __name__ == "__main__":
    unittest.main()
