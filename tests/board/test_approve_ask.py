import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "approve_ask", REPO / "scripts" / "board" / "approve-ask.py")
approve_ask = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(approve_ask)


def run(*argv):
    """main() under --dry-run -> (rc, parsed payload)."""
    buf = io.StringIO()
    old = sys.argv
    sys.argv = ["approve-ask.py", *argv, "--dry-run"]
    try:
        with contextlib.redirect_stdout(buf):
            rc = approve_ask.main()
    finally:
        sys.argv = old
    return rc, json.loads(buf.getvalue())


class Options(unittest.TestCase):
    def test_default_menu_is_approve_hold(self):
        rc, body = run("card-x", "Dispatch it?")
        self.assertEqual(rc, 0)
        self.assertEqual(body["request_id"], "approve-card-x")
        self.assertEqual(body["from"], "ada")
        self.assertEqual(body["to"], "tony")
        acts = [(o["id"], o["action"]) for o in body["options"]]
        self.assertEqual(acts, [("approve", "queue"), ("hold", "hold")])

    def test_approve_action_retry_swaps_label_and_action(self):
        _, body = run("card-x", "Retry?", "--approve-action", "retry")
        self.assertEqual(body["options"][0]["action"], "retry")
        self.assertIn("retry", body["options"][0]["label"])

    def test_extra_option_appended(self):
        _, body = run("card-x", "?", "--extra-option",
                      "close|Close — mark done|close")
        self.assertEqual(body["options"][-1],
                         {"id": "close", "label": "Close — mark done",
                          "action": "close"})

    def test_options_json_replaces_menu(self):
        _, body = run("card-x", "?", "--options-json",
                      '["keep", {"id": "g", "label": "Go", '
                      '"action": "queue"}]')
        self.assertEqual(body["options"][0], "keep")
        self.assertEqual(body["options"][1]["action"], "queue")

    def test_suggested_and_request_id_pass_through(self):
        _, body = run("card-x", "?", "--suggested", "approve",
                      "--request-id", "gate-1")
        self.assertEqual(body["suggested"], "approve")
        self.assertEqual(body["request_id"], "gate-1")


class ParseExtra(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(approve_ask.parse_extra("a|A|none"),
                         {"id": "a", "label": "A", "action": "none"})

    def test_rejects_bad_action(self):
        with self.assertRaises(Exception):
            approve_ask.parse_extra("a|A|explode")

    def test_rejects_malformed(self):
        with self.assertRaises(Exception):
            approve_ask.parse_extra("a|only-two")


if __name__ == "__main__":
    unittest.main()
