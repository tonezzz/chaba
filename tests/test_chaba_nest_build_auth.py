import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/home-assistant/ada_ha_auth.py"
SPEC = importlib.util.spec_from_file_location("ada_ha_auth", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ChabaNestBuildAuthTests(unittest.TestCase):
    def write_auth(self, path, records):
        path.write_text(json.dumps({"data": {"refresh_tokens": records}}))

    def test_uses_the_documented_ada_live_refresh_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "auth.json"
            self.write_auth(auth_path, [
                {"client_name": "ada-ha-live", "token": "valid-refresh"},
                {"client_name": "unrelated", "token": "other-refresh"},
            ])
            response = io.BytesIO(b'{"access_token":"short-lived"}')
            captured = {}

            def fake_urlopen(request):
                captured["request"] = request
                return response

            token = MODULE.get_access_token(
                "http://127.0.0.1:8125",
                auth_path=auth_path,
                urlopen=fake_urlopen,
            )

            self.assertEqual(token, "short-lived")
            self.assertIn(b"refresh_token=valid-refresh", captured["request"].data)

    def test_missing_refresh_token_fails_with_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "auth.json"
            self.write_auth(auth_path, [
                {"client_name": "unrelated", "token": "other-refresh"},
            ])
            with self.assertRaisesRegex(RuntimeError, "ada-ha-live"):
                MODULE.get_access_token("http://127.0.0.1:8125", auth_path=auth_path)


if __name__ == "__main__":
    unittest.main()
