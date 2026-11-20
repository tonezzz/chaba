"""Unit tests for the allowlisted OpenCode command publisher (card
ada-opencode-command-publisher-20261108): opencode_command.handle ops
(preview/validate/publish/sync/verify), confirm+sha gates, atomic
deploy, and the board-api /opencode-command door's error mapping.

Local mode only (OPENCODE_COMMAND_LOCAL=1 + tmp repo/deploy paths);
the ssh branch is covered by a mocked subprocess.run — no network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]


def _load(name="opencode_command"):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "board" / "opencode_command.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CANON = ("---\n"
         "description: test command\n"
         "---\n\n"
         "body with /ada sweep and Sweep Verdicts calling the "
         "`question` tool\n")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.oc = _load()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        self.deploy = root / "ws" / ".opencode" / "commands" / "cmd.md"
        (self.repo / "stacks/x/commands").mkdir(parents=True)
        self.deploy.parent.mkdir(parents=True)
        self.oc.COMMANDS["test"] = {
            "repo_rel": "stacks/x/commands/cmd.md",
            "deploy_host": "testhost",
            "deploy_path": str(self.deploy),
            "max_bytes": 65536,
            "frontmatter": True,
            "required_markers": ["/ada sweep", "Sweep Verdicts",
                                 "`question` tool"],
        }
        self._env = dict(os.environ)
        os.environ["OPENCODE_COMMAND_REPO"] = str(self.repo)
        os.environ["OPENCODE_COMMAND_LOCAL"] = "1"
        self.name = "test"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.oc.COMMANDS.pop("test", None)
        self.tmp.cleanup()

    def canon_path(self):
        return self.repo / "stacks/x/commands/cmd.md"

    def write_canon(self, text=CANON):
        self.canon_path().write_text(text)


class ValidateTest(Base):
    def test_valid_content(self):
        r = self.oc.handle({"op": "validate", "name": self.name,
                            "content": CANON})
        self.assertTrue(r["valid"])
        self.assertEqual(r["sha256"], _sha(CANON))

    def test_missing_required_marker(self):
        bad = CANON.replace("Sweep Verdicts", "Sweep")
        r = self.oc.handle({"op": "validate", "name": self.name,
                            "content": bad})
        self.assertFalse(r["valid"])
        self.assertTrue(any("Sweep Verdicts" in e
                            for e in r["errors"]))

    def test_bad_frontmatter(self):
        r = self.oc.handle({"op": "validate", "name": self.name,
                            "content": "no frontmatter\n/ada sweep "
                                       "Sweep Verdicts `question` tool"})
        self.assertFalse(r["valid"])

    def test_unknown_name_rejected(self):
        with self.assertRaises(ValueError):
            self.oc.handle({"op": "validate", "name": "../etc/passwd"})

    def test_bad_op_rejected(self):
        with self.assertRaises(ValueError):
            self.oc.handle({"op": "exec", "name": self.name})


class PreviewVerifyTest(Base):
    def test_preview_diff_and_sync_state(self):
        self.write_canon()
        self.deploy.write_text("old deployed\n")
        r = self.oc.handle({"op": "preview", "name": self.name})
        self.assertFalse(r["in_sync"])
        self.assertIn("old deployed", r["diff"])
        self.assertEqual(r["canonical_sha"], _sha(CANON))

    def test_verify_match_and_mismatch(self):
        self.write_canon()
        self.deploy.write_text(CANON)
        r = self.oc.handle({"op": "verify", "name": self.name})
        self.assertTrue(r["match"])
        self.deploy.write_text("drift\n")
        r = self.oc.handle({"op": "verify", "name": self.name})
        self.assertFalse(r["match"])

    def test_missing_deployed_reports_none(self):
        self.write_canon()
        r = self.oc.handle({"op": "verify", "name": self.name})
        self.assertIsNone(r["deployed_sha"])
        self.assertFalse(r["match"])


class PublishTest(Base):
    def test_publish_requires_confirm(self):
        with self.assertRaises(ValueError):
            self.oc.handle({"op": "publish", "name": self.name,
                            "content": CANON,
                            "expect_sha": _sha(CANON)})

    def test_publish_requires_expect_sha(self):
        with self.assertRaises(ValueError):
            self.oc.handle({"op": "publish", "name": self.name,
                            "content": CANON, "confirm": True,
                            "expect_sha": ""})

    def test_publish_sha_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            self.oc.handle({"op": "publish", "name": self.name,
                            "content": CANON, "confirm": True,
                            "expect_sha": _sha("other")})

    def test_publish_invalid_content_rejected(self):
        bad = "junk without markers"
        with self.assertRaises(ValueError):
            self.oc.handle({"op": "publish", "name": self.name,
                            "content": bad, "confirm": True,
                            "expect_sha": _sha(bad)})

    def test_publish_writes_and_hooks(self):
        calls = []
        r = self.oc.handle({"op": "publish", "name": self.name,
                            "content": CANON, "confirm": True,
                            "expect_sha": _sha(CANON)},
                           commit_hook=calls.append)
        self.assertTrue(r["changed"])
        self.assertEqual(r["commit"], "queued")
        self.assertEqual(self.canon_path().read_text(), CANON)
        self.assertEqual(calls, [self.canon_path()])

    def test_publish_idempotent_no_hook(self):
        self.write_canon()
        calls = []
        r = self.oc.handle({"op": "publish", "name": self.name,
                            "content": CANON, "confirm": True,
                            "expect_sha": _sha(CANON)},
                           commit_hook=calls.append)
        self.assertFalse(r["changed"])
        self.assertEqual(calls, [])


class SyncTest(Base):
    def test_sync_requires_confirm(self):
        self.write_canon()
        with self.assertRaises(ValueError):
            self.oc.handle({"op": "sync", "name": self.name})

    def test_sync_deploys_and_verifies(self):
        self.write_canon()
        r = self.oc.handle({"op": "sync", "name": self.name,
                            "confirm": True})
        self.assertTrue(r["match"])
        self.assertEqual(self.deploy.read_text(), CANON)
        self.assertFalse(list(self.deploy.parent.glob("*.new-*")),
                         "sync must not leave temp files")

    def test_sync_expect_sha_toctou_guard(self):
        self.write_canon()
        with self.assertRaises(ValueError):
            self.oc.handle({"op": "sync", "name": self.name,
                            "confirm": True,
                            "expect_sha": _sha("stale preview")})

    def test_sync_idempotent(self):
        self.write_canon()
        self.deploy.write_text(CANON)
        r = self.oc.handle({"op": "sync", "name": self.name,
                            "confirm": True})
        self.assertFalse(r["changed"])

    def test_sync_without_canonical_fails(self):
        with self.assertRaises(self.oc.PublishError):
            self.oc.handle({"op": "sync", "name": self.name,
                            "confirm": True})


class SshTransportTest(Base):
    """Remote mode: deploy_host != hostname, no local override."""

    def setUp(self):
        super().setUp()
        os.environ.pop("OPENCODE_COMMAND_LOCAL", None)
        self.oc.COMMANDS["test"]["deploy_host"] = "idc02"

    def test_remote_read_uses_fixed_argv(self):
        self.write_canon()
        seen = []

        def fake_run(argv, **kw):
            seen.append(argv)
            if "cat" in argv[-1]:
                return subprocess.CompletedProcess(
                    argv, 0, stdout=b"remote-bytes", stderr=b"")
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with mock.patch.object(self.oc.subprocess, "run", fake_run), \
             mock.patch.object(self.oc.socket, "gethostname",
                               return_value="otherhost"):
            data = self.oc.read_deployed("test")
        self.assertEqual(data, b"remote-bytes")
        argv = seen[0]
        self.assertEqual(argv[:2], ["ssh", "-o"])
        self.assertIn("idc02", argv)
        self.assertIn("cat -- ", argv[-1])
        self.assertIn(str(self.deploy), argv[-1])

    def test_remote_write_pipes_stdin_then_mv(self):
        seen = []

        def fake_run(argv, input=None, **kw):
            seen.append((argv, input))
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with mock.patch.object(self.oc.subprocess, "run", fake_run), \
             mock.patch.object(self.oc.socket, "gethostname",
                               return_value="otherhost"):
            self.oc.write_deployed("test", b"payload")
        argv, stdin = seen[0]
        self.assertEqual(stdin, b"payload")
        remote = argv[-1]
        self.assertIn("cat > ", remote)
        self.assertIn("mv -f -- ", remote)
        self.assertIn(".new-", remote)

    def test_remote_failure_raises_publish_error(self):
        def fake_run(argv, **kw):
            return subprocess.CompletedProcess(
                argv, 255, b"", b"ssh: connect failed")

        with mock.patch.object(self.oc.subprocess, "run", fake_run), \
             mock.patch.object(self.oc.socket, "gethostname",
                               return_value="otherhost"):
            with self.assertRaises(self.oc.PublishError):
                self.oc.read_deployed("test")


class BoardApiDoorTest(Base):
    """The /opencode-command door: hook wiring + error mapping."""

    def test_door_queues_commit_and_maps_errors(self):
        spec = importlib.util.spec_from_file_location(
            "board_api_opc", REPO / "scripts" / "board" / "board-api.py")
        api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(api)
        api.opc.COMMANDS["test"] = self.oc.COMMANDS["test"]
        queued = []
        try:
            with mock.patch.object(api, "_queue_commit",
                                   lambda p, label:
                                   queued.append((p, label))):
                r = api.do_opencode_command(
                    {"op": "publish", "name": self.name,
                     "content": CANON,
                     "confirm": True, "expect_sha": _sha(CANON)},
                    "devin")
            self.assertTrue(r["changed"])
            self.assertEqual(queued[0][0], self.canon_path())
            self.assertIn("opencode-command", queued[0][1])
            self.assertEqual(r["actor"], "devin")
            # invalid op -> ValueError (400 at the door)
            with self.assertRaises(ValueError):
                api.do_opencode_command(
                    {"op": "nope", "name": self.name}, "devin")
            # remote failure -> UpstreamError (502 at the door)
            with mock.patch.object(
                    api.opc, "read_deployed",
                    side_effect=api.opc.PublishError("down")):
                with self.assertRaises(api.UpstreamError):
                    api.do_opencode_command(
                        {"op": "verify", "name": self.name}, "devin")
        finally:
            api.opc.COMMANDS.pop("test", None)

    def test_door_path_registered(self):
        spec = importlib.util.spec_from_file_location(
            "board_api_opc2", REPO / "scripts" / "board" / "board-api.py")
        api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(api)
        self.assertIn("/opencode-command", api.REMOTE_WRITE_PATHS)


if __name__ == "__main__":
    unittest.main()
