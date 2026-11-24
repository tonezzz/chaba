import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/home-assistant/sync-ada-ha-chaba-admin.py"
SPEC = importlib.util.spec_from_file_location("ada_dashboard_snapshot", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdaDashboardSnapshotTests(unittest.TestCase):
    def test_extracts_dashboard_config_from_home_assistant_storage_envelope(self):
        config = {"views": [{"title": "Board", "path": "board"}]}
        self.assertEqual(
            MODULE.extract_dashboard_config({
                "version": 1,
                "key": "lovelace.chaba_admin",
                "data": {"config": config},
            }),
            config,
        )

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

    def test_keeps_pfg_charts_series_key_but_redacts_secret_key_elsewhere(self):
        source = {
            "views": [
                {
                    "cards": [
                        {
                            "type": "custom:pfg3d-card",
                            "pfg_charts": {
                                "1,1": [{"type": "bar3d", "key": "nobito"}]
                            },
                        }
                    ]
                }
            ],
            "key": "real-secret",
        }
        counts = {"redacted": 0}
        sanitized = MODULE.sanitize_snapshot(source, counts)

        self.assertEqual(
            sanitized["views"][0]["cards"][0]["pfg_charts"]["1,1"][0]["key"],
            "nobito",
        )
        self.assertEqual(sanitized["key"], "<redacted>")
        self.assertEqual(counts["redacted"], 1)


if __name__ == "__main__":
    unittest.main()
