import contextlib
import importlib.util
import io
import json
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

    def test_request_dict_option_with_action(self):
        call = self.invoke(
            "request", "card-one", "Pick", "--options", "plain",
            "--option", "go|Go now|queue",
            "--option", "later|Later|hold",
            "--option", "bare-word")
        self.assertEqual(call.args, ("POST", "/request", {
            "id": "card-one", "from": "devin", "ask": "Pick",
            "options": ["plain",
                        {"id": "go", "label": "Go now", "action": "queue"},
                        {"id": "later", "label": "Later", "action": "hold"},
                        "bare-word"]
        }, None))

    def test_request_dict_option_bad_action_rejected(self):
        result = None
        with mock.patch.object(sys, "argv",
                               ["board-cli.py", "request", "c", "q",
                                "--option", "x|X|explode"]), \
                mock.patch.object(self.cli, "call") as call, \
                contextlib.redirect_stdout(io.StringIO()):
            result = self.cli.main()
        self.assertEqual(result, 2)
        call.assert_not_called()

    def test_request_dict_option_id_label_only(self):
        call = self.invoke("request", "card-one", "Pick",
                           "--option", "a|Alpha")
        self.assertEqual(call.args[2]["options"],
                         [{"id": "a", "label": "Alpha"}])

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


class TestBoardCliFallback(unittest.TestCase):
    """Loopback default falls back to the tailnet endpoint on connect
    failure; explicit BOARD_API/--api never falls back."""

    def setUp(self):
        path = Path(__file__).resolve().parents[2] / "scripts/board/board-cli.py"
        spec = importlib.util.spec_from_file_location("board_cli", path)
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)

    def _resp(self, payload=b'{"ok": true}'):
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__.return_value = resp
        return resp

    def test_loopback_refused_falls_back_to_tailnet(self):
        self.cli.API = self.cli.LOOPBACK_API
        with mock.patch.object(self.cli.urllib.request, "urlopen",
                               side_effect=[OSError("refused"),
                                            self._resp()]) as uo:
            out = self.cli.call("GET", "/cards", None, None)
        self.assertEqual(out, {"ok": True})
        self.assertEqual(uo.call_count, 2)
        self.assertIn(self.cli.TAILNET_API,
                      uo.call_args_list[1].args[0].full_url)

    def test_http_error_does_not_fall_back(self):
        self.cli.API = self.cli.LOOPBACK_API
        err = self.cli.urllib.error.HTTPError(
            self.cli.LOOPBACK_API, 503, "unavailable", {}, None)
        with mock.patch.object(self.cli.urllib.request, "urlopen",
                               side_effect=err) as uo:
            with self.assertRaises(self.cli.urllib.error.HTTPError):
                self.cli.call("GET", "/cards", None, None)
        self.assertEqual(uo.call_count, 1)

    def test_explicit_api_does_not_fall_back(self):
        self.cli.API = "http://board-api.example:9999"
        with mock.patch.object(self.cli.urllib.request, "urlopen",
                               side_effect=OSError("refused")) as uo:
            with self.assertRaises(OSError):
                self.cli.call("GET", "/cards", None, None)
        self.assertEqual(uo.call_count, 1)


class TestBoardCliTimeout(unittest.TestCase):
    """board-cli-post-timeout-vs-big-card-writes: every HTTP path must
    outwait a large-card board-api write so a retry cannot duplicate it."""

    def setUp(self):
        path = Path(__file__).resolve().parents[2] / "scripts/board/board-cli.py"
        spec = importlib.util.spec_from_file_location("board_cli", path)
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)

    @staticmethod
    def _resp(payload=b'{"ok": true}'):
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__.return_value = resp
        return resp

    def test_default_timeout_outwaits_server_lock_wait(self):
        # board-api LOCK_WAIT_S=25s; render + scoped commit tail follows
        self.assertGreaterEqual(self.cli.HTTP_TIMEOUT_S, 120)

    def test_http_uses_configured_timeout(self):
        with mock.patch.object(self.cli.urllib.request, "urlopen",
                               return_value=self._resp()) as uo:
            out = self.cli._http("POST", "/comment", b"{}", self.cli.LOOPBACK_API)
        self.assertEqual(out, {"ok": True})
        self.assertEqual(uo.call_args.kwargs["timeout"], self.cli.HTTP_TIMEOUT_S)

    def test_api_mode_uses_configured_timeout(self):
        env = json.dumps({"method": "POST", "path": "/comment",
                          "payload": {"id": "c"}}).encode()
        stdin = mock.MagicMock()
        stdin.buffer.read.return_value = env
        with mock.patch.object(sys, "stdin", stdin), \
                mock.patch.object(sys, "stdout", new_callable=io.StringIO), \
                mock.patch.object(self.cli.urllib.request, "urlopen",
                                  return_value=self._resp()) as uo:
            self.assertEqual(self.cli.api_mode(), 0)
        self.assertEqual(uo.call_args.kwargs["timeout"], self.cli.HTTP_TIMEOUT_S)
