import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/home-assistant/mutate-ada-ha-cline-tab.py"
SPEC = importlib.util.spec_from_file_location("ada_cline_dashboard", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdaHaClineDashboardTests(unittest.TestCase):
    def dashboard(self):
        return {
            "views": [
                {"title": "Pair", "path": "pair", "cards": []},
                {"title": "Board", "path": "board", "type": "panel", "cards": []},
                {"title": "DevNest", "path": "devnest", "cards": []},
            ]
        }

    def test_inserts_full_page_panel_after_board(self):
        config = self.dashboard()
        MODULE.mutate(config)

        views = config["views"]
        self.assertEqual([view["path"] for view in views], [
            "pair", "board", "cline", "devnest",
        ])
        self.assertEqual(views[2]["type"], "panel")
        self.assertEqual(views[2]["cards"][0]["type"], "iframe")
        self.assertEqual(
            views[2]["cards"][0]["url"],
            "https://cline.surf-thailand.com/?v=1",
        )
        self.assertNotIn("api_key", views[2]["cards"][0]["url"])

    def test_is_idempotent_and_repositions_existing_cline_view(self):
        config = self.dashboard()
        config["views"].append({
            "title": "Cline",
            "path": "cline",
            "type": "panel",
            "cards": [{"type": "iframe", "url": "https://old.example/"}],
        })
        MODULE.mutate(config)
        MODULE.mutate(config)

        self.assertEqual([view["path"] for view in config["views"]], [
            "pair", "board", "cline", "devnest",
        ])
        self.assertEqual(
            config["views"][2]["cards"][0]["url"],
            "https://cline.surf-thailand.com/?v=1",
        )

    def test_refuses_to_save_if_board_view_is_missing(self):
        with self.assertRaisesRegex(ValueError, "no Board view"):
            MODULE.mutate({"views": [{"title": "Pair", "path": "pair"}]})


if __name__ == "__main__":
    unittest.main()
