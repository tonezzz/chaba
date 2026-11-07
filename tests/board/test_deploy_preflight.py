"""Tests for scripts/board/deploy-preflight.py (card KNB-1090).

The deploy gate is the human-approval stage between merge and prod:
preflight evidence -> Tony's request -> approve runs the registry deploy
-> health surface verified. Fail-closed: unknown targets, t4 cards,
non-approved answers, and missing artifacts must never deploy.

No network — api_post/run_deploy/verify_surface are mocked; card YAML
lives in a tmpdir via monkeypatched CARD_DIR/LOCK.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))

spec = importlib.util.spec_from_file_location(
    "deploy_preflight",
    REPO / "scripts" / "board" / "deploy-preflight.py")
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)


def make_card(tmp: Path, cid: str, **kw) -> Path:
    card = {
        "id": cid,
        "title": cid,
        "column": "review",
        "action": {"type": "dispatch", "status": "done"},
        "deploy": {"target": "ada-voice-prod"},
    }
    card.update(kw)
    p = tmp / f"{cid}.yml"
    p.write_text(yaml.safe_dump(card, sort_keys=False))
    return p


def load_card(p: Path) -> dict:
    return yaml.safe_load(p.read_text())


class DeployPreflightCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._card_dir = dp.CARD_DIR
        self._lock = dp.LOCK
        dp.CARD_DIR = self.tmp
        dp.LOCK = self.tmp / "board-api.lock"
        dp.LOCK.touch()

    def tearDown(self):
        dp.CARD_DIR = self._card_dir
        dp.LOCK = self._lock

    # ---------------------------------------------------------- decide()

    def test_no_deploy_block_skips(self):
        p = make_card(self.tmp, "plain-card", deploy=None)
        card = load_card(p)
        card.pop("deploy")
        action, _ = dp.decide(card, "plain-card")
        self.assertEqual(action, "skip")

    def test_unknown_target_fails_closed(self):
        p = make_card(self.tmp, "bad-target",
                      deploy={"target": "rm-rf-prod"})
        card = load_card(p)
        action, pl = dp.decide(card, "bad-target")
        self.assertEqual(action, "error")
        self.assertEqual(card["deploy"]["status"], "error")

    def test_t4_never_touched(self):
        p = make_card(self.tmp, "t4-card", autonomy="t4")
        card = load_card(p)
        action, _ = dp.decide(card, "t4-card")
        self.assertEqual(action, "skip")

    def test_wrong_column_skips(self):
        p = make_card(self.tmp, "backlog-card", column="backlog")
        card = load_card(p)
        action, _ = dp.decide(card, "backlog-card")
        self.assertEqual(action, "skip")

    def test_action_not_done_skips(self):
        p = make_card(self.tmp, "running-card",
                      action={"type": "dispatch", "status": "running"})
        card = load_card(p)
        action, _ = dp.decide(card, "running-card")
        self.assertEqual(action, "skip")

    def test_deployed_is_terminal(self):
        p = make_card(self.tmp, "done-deploy",
                      deploy={"target": "ada-voice-prod",
                              "status": "deployed"})
        card = load_card(p)
        action, _ = dp.decide(card, "done-deploy")
        self.assertEqual(action, "skip")

    def test_failed_once_does_not_loop(self):
        p = make_card(self.tmp, "failed-deploy",
                      deploy={"target": "ada-voice-prod",
                              "status": "failed", "failed_at": "x"})
        card = load_card(p)
        action, _ = dp.decide(card, "failed-deploy")
        self.assertEqual(action, "skip")

    def test_no_request_raises_preflight(self):
        p = make_card(self.tmp, "fresh-card")
        card = load_card(p)
        action, pl = dp.decide(card, "fresh-card")
        self.assertEqual(action, "preflight")
        self.assertEqual(card["deploy"]["status"], "preflight")
        self.assertEqual(pl["dep"]["request_id"], "deploy-fresh-card")
        self.assertIn("merge_sha", pl["ev"])

    def test_open_request_waits(self):
        p = make_card(self.tmp, "pending-card", requests=[{
            "id": "deploy-pending-card", "ask": "Deploy?",
            "status": "open", "options": dp.REQUEST_OPTS}])
        card = load_card(p)
        action, _ = dp.decide(card, "pending-card")
        self.assertEqual(action, "wait")

    def test_approve_answer_triggers_deploy(self):
        p = make_card(self.tmp, "ok-card", requests=[{
            "id": "deploy-ok-card", "ask": "Deploy?",
            "status": "answered", "answer": "approve — run the deploy now"}])
        card = load_card(p)
        action, pl = dp.decide(card, "ok-card")
        self.assertEqual(action, "deploy")
        self.assertEqual(pl["dep"]["target"], "ada-voice-prod")

    def test_hold_answer_never_deploys(self):
        p = make_card(self.tmp, "hold-card", requests=[{
            "id": "deploy-hold-card", "ask": "Deploy?",
            "status": "answered", "answer": "hold — keep merged"}])
        card = load_card(p)
        action, _ = dp.decide(card, "hold-card")
        self.assertEqual(action, "held")
        self.assertEqual(card["deploy"]["status"], "held")

    def test_raise_request_payload_is_api_valid(self):
        # Regression: suggested=1 400'd the first live raise — do_request
        # requires suggested to be one of options[] verbatim.
        seen = {}

        def fake_post(path, payload):
            seen.update(payload)

        with mock.patch.object(dp, "api_post", fake_post):
            dp.raise_request("cid-x", {"target": "ada-voice-prod"},
                             {"merge_sha": "abc", "files": "f",
                              "tests": "t"})
        self.assertIn(seen["suggested"], seen["options"])
        self.assertEqual(seen["request_id"], "deploy-cid-x")

    def test_unparsed_answer_holds_not_deploys(self):
        p = make_card(self.tmp, "weird-card", requests=[{
            "id": "deploy-weird-card", "ask": "Deploy?",
            "status": "answered", "answer": "maybe later?"}])
        card = load_card(p)
        action, _ = dp.decide(card, "weird-card")
        self.assertEqual(action, "held")

    # ------------------------------------------------------- run_deploy()

    def test_run_deploy_uses_registry_command_only(self):
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            class R:
                returncode = 0
                stdout = "deploy ok"
                stderr = ""
            return R()

        dep = {"target": "ada-voice-prod"}
        with mock.patch.object(dp.subprocess, "run", side_effect=fake_run):
            res = dp.run_deploy(dep)
        self.assertTrue(res["ok"])
        # idc03 is not this host -> ssh path with fixed registry command
        self.assertIn("idc03", calls[0])
        self.assertIn("deploy-ada.sh", calls[0][-1])

    def test_verify_surface_requires_ok_true(self):
        tgt = {"verify_url": "http://x", "verify_ok_key": "ok"}

        class Resp:
            status = 200
            def read(self):
                return b'{"ok": true, "degraded": false}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        with mock.patch.object(dp.urllib.request, "urlopen",
                               return_value=Resp()):
            self.assertTrue(dp.verify_surface(tgt)["ok"])

        class BadResp(Resp):
            def read(self):
                return b'{"ok": false}'

        with mock.patch.object(dp.urllib.request, "urlopen",
                               return_value=BadResp()), \
                mock.patch.object(dp, "VERIFY_WINDOW_S", 0):
            self.assertFalse(dp.verify_surface(tgt)["ok"])

    def test_verify_surface_retries_through_warmup(self):
        # Regression: post-restart /api/health needs ~60-90s; the first
        # live deploy false-failed on a single-shot verify (2026-11-07).
        tgt = {"verify_url": "http://x", "verify_ok_key": "ok"}

        class Resp:
            status = 200
            def __init__(self, body):
                self._body = body
            def read(self):
                return self._body
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        calls = []

        def flaky(url, timeout=0):
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionRefusedError("warming up")
            return Resp(b'{"ok": true}')

        with mock.patch.object(dp.urllib.request, "urlopen",
                               side_effect=flaky), \
                mock.patch.object(dp, "VERIFY_WINDOW_S", 60), \
                mock.patch.object(dp, "VERIFY_INTERVAL_S", 0), \
                mock.patch.object(dp.time, "sleep", lambda s: None):
            self.assertTrue(dp.verify_surface(tgt)["ok"])
            self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
