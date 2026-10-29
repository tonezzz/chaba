import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/home-assistant/sync-ada-ha-chaba-admin.py"
SPEC = importlib.util.spec_from_file_location("ada_dashboard_snapshot", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdaDashboardSnapshotTests(unittest.TestCase):
    def test_redacts_sensitive_query_values_and_fields(self):
        source = {
            "views": [
                {
                    "cards": [
                        {
                            "type": "iframe",
                            "url": "https://cms.example/view?tab=pages&api_key=secret-value",
                        }
                    ]
                }
            ],
            "api_key": "another-secret",
        }
        counts = {"redacted": 0}
        sanitized = MODULE.sanitize_snapshot(source, counts)
        serialized = json.dumps(sanitized)

        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("another-secret", serialized)
        self.assertIn("api_key", serialized)
        self.assertIn("tab", serialized)
        self.assertEqual(counts["redacted"], 2)

    def test_leaves_noncredential_urls_unchanged(self):
        url = "https://cline.surf-thailand.com/?v=1"
        self.assertEqual(MODULE.sanitize_snapshot(url), url)


if __name__ == "__main__":
    unittest.main()
