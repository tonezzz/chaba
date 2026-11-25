import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/home-assistant/mutate-ada-ha-devnest-tab.py"
SPEC = importlib.util.spec_from_file_location("ada_devnest_dashboard", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdaHaDevNestDashboardTests(unittest.TestCase):
    def dashboard(self):
        return {
            "views": [
                {"title": "Board", "path": "board", "type": "panel", "cards": []},
                {
                    "title": "DevNest",
                    "path": "devnest",
                    "type": "panel",
                    "cards": [{"type": "iframe", "url": "https://blank.example/"}],
                },
                {
                    "title": "Ada Pages",
                    "path": "ada-pages",
                    "type": "panel",
                    "cards": [{
                        "type": "iframe",
                        "url": (
                            "https://idc03.example/apps/ha/ada-tony/cms/"
                            "?api_key=example-viewer-key"
                        ),
                    }],
                },
            ]
        }

    def test_repoints_devnest_to_embedded_report_reusing_ada_pages_key(self):
        config = self.dashboard()
        MODULE.mutate(config)
        url = config["views"][1]["cards"][0]["url"]

        self.assertEqual(
            url,
            "https://idc03.example/apps/ha/ada-tony/cms/"
            "?api_key=example-viewer-key&embed=1#/devnest-visual-map",
        )
        self.assertEqual(config["views"][0]["path"], "board")
        self.assertEqual(config["views"][2]["path"], "ada-pages")

    def test_mutation_is_idempotent(self):
        config = self.dashboard()
        MODULE.mutate(config)
        first = config["views"][1]["cards"][0]["url"]
        MODULE.mutate(config)
        self.assertEqual(config["views"][1]["cards"][0]["url"], first)

    def test_refuses_a_missing_viewer_key(self):
        config = self.dashboard()
        config["views"][2]["cards"][0]["url"] = (
            "https://idc03.example/apps/ha/ada-tony/cms/"
        )
        with self.assertRaisesRegex(ValueError, "no reusable CMS viewer key"):
            MODULE.mutate(config)


if __name__ == "__main__":
    unittest.main()
