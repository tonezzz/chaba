import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


class TestBoardCli(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[2] / "scripts/board/board-cli.py"
        spec = importlib.util.spec_from_file_location("board_cli", path)
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)

    def invoke(self, *args):
        with mock.patch.object(sys, "argv", ["board-cli.py", *args]), \
                mock.patch.object(self.cli, "call", return_value={"ok": True}) as call, \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            result = self.cli.main()
        self.assertEqual(result, 0)
        return call.call_args

    def test_request_uses_ask_and_preserves_options_and_transport(self):
        call = self.invoke("--ssh", "idc03", "request", "card-one", "Proceed?", "--options", "Yes|No")
        self.assertEqual(call.args, ("POST", "/request", {
            "id": "card-one", "from": "devin", "ask": "Proceed?", "options": ["Yes", "No"]
        }, "idc03"))

    def test_respond_routes_card_and_uses_answer(self):
        call = self.invoke("--ssh", "idc03", "respond", "card-one", "req-one", "Yes")
        self.assertEqual(call.args, ("POST", "/respond", {
            "id": "card-one", "request_id": "req-one", "from": "devin", "answer": "Yes"
        }, "idc03"))

    def test_respond_requires_card_id(self):
        with self.assertRaises(SystemExit) as error:
            self.invoke("respond", "req-one", "Yes")
        self.assertEqual(error.exception.code, 2)

    def test_comment_keeps_text(self):
        call = self.invoke("comment", "card-one", "Checked")
        self.assertEqual(call.args, ("POST", "/comment", {
            "id": "card-one", "from": "devin", "text": "Checked"
        }, None))
