"""Tests for runner-agent's per-executor claim caps + remote-lane
load-gate exemption (card runner-per-executor-caps, OPS-1284).

Problem: remote-async executors (jules ~1h Google-side wait,
nlm_batch, kk_mac_local) held RUNNER_CAP slots while doing ~zero
local work — omen at 3/3 jules meant zero local dispatch capacity —
and heavyweight claims deferred at RUNNER_MAX_LOAD_PC even though
remote claims put no load on the host.

Contract under test:
  - RUNNER_CAP stays the LOCAL-executor ceiling; RUNNER_REMOTE_CAP
    (default 6) counts REMOTE_EXECUTORS {jules, nlm_batch,
    kk_mac_local} separately — a host holds cap_local + cap_remote
    claims concurrently.
  - Remote claims are exempt from RUNNER_MAX_LOAD_PC (the
    RUNNER_SCRIPT_MAX_LOAD_PC pattern applied per class), bounded by
    RUNNER_REMOTE_MAX_LOAD_PC (default 0 = load-independent) and the
    lanes' own quotas.
  - claim_pass notes which cap/gate held per declined card.
"""

from __future__ import annotations

import importlib.util
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent_rcap",
                                                  SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["runner_agent_rcap"] = mod
    spec.loader.exec_module(mod)
    return mod


def _card(cid: str, **action) -> dict:
    a = {"type": "dispatch", "status": "queued"}
    a.update(action)
    return {"id": cid, "column": "backlog", "title": f"t-{cid}",
            "action": a}


class ClaimExecutorTest(unittest.TestCase):
    """claim_executor resolves the executor a claim will run under —
    the value st[] entries carry for _cap_counts."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in
                       ("kk_mac_servable", "dr_module")}
        m.kk_mac_servable = lambda: False
        m.dr_module = lambda: None
        self._saved_env = os.environ.get("JEV_LANE")
        os.environ["JEV_LANE"] = "0"

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.mod, k, v)
        if self._saved_env is None:
            os.environ.pop("JEV_LANE", None)
        else:
            os.environ["JEV_LANE"] = self._saved_env

    def test_nlm_batch_executor_is_remote(self):
        self.assertEqual(
            self.mod.claim_executor(_card("c", executor="nlm_batch")),
            "nlm_batch")

    def test_nlm_batch_lane_pin_is_remote(self):
        self.assertEqual(
            self.mod.claim_executor(_card("c", lane="nlm_batch")),
            "nlm_batch")

    def test_kk_mac_local_servable_is_remote(self):
        self.mod.kk_mac_servable = lambda: True
        self.assertEqual(
            self.mod.claim_executor(
                _card("c", executor="kk_mac_local",
                      task_class="summary")),
            "kk_mac_local")

    def test_kk_mac_local_fallback_is_local(self):
        # kk_mac_tried consumed or lane unservable -> the claim runs
        # the local lane cascade, so it must draw the LOCAL cap
        self.mod.kk_mac_servable = lambda: True
        self.assertEqual(
            self.mod.claim_executor(
                _card("c", executor="kk_mac_local", kk_mac_tried=True,
                      task_class="summary")),
            "")
        self.mod.kk_mac_servable = lambda: False
        self.assertEqual(
            self.mod.claim_executor(
                _card("c", executor="kk_mac_local",
                      task_class="summary")),
            "")

    def test_devin_opencode_script_are_local(self):
        for ex in ("devin", "opencode", "claude"):
            self.assertEqual(
                self.mod.claim_executor(_card("c", executor=ex)), ex)
        self.assertEqual(
            self.mod.claim_executor(_card("c", type="script")), "script")
        self.assertEqual(
            self.mod.claim_executor(_card("c", type="container")),
            "container")
        self.assertEqual(self.mod.claim_executor(_card("c")), "")


class CapCountsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_counts_split_by_recorded_executor(self):
        st = {
            "a": {"unit": "u1", "type": "dispatch"},               # no ex -> local
            "b": {"unit": "u2", "type": "dispatch", "ex": ""},    # devin path
            "c": {"unit": "u3", "type": "dispatch",
                  "ex": "nlm_batch"},                            # remote
            "d": {"unit": "u4", "type": "dispatch",
                  "ex": "kk_mac_local"},                         # remote
        }
        self.assertEqual(self.mod._cap_counts(st), (2, 2))

    def test_capacity_reason_only_fires_when_both_full(self):
        m = self.mod
        saved = (m.CAP, m.REMOTE_CAP, m.ratelimit_reason,
                 m.overloaded, m.WAITING_KILL)
        try:
            m.CAP = 1
            m.REMOTE_CAP = 1
            m.ratelimit_reason = lambda: ""
            m.overloaded = lambda pc=None: False
            local_full = {"a": {"unit": "u", "type": "dispatch"}}
            remote_full = {"b": {"unit": "u", "type": "dispatch",
                                 "ex": "nlm_batch"}}
            # local saturated, remote free -> no capacity refusal
            self.assertEqual(m._capacity_reason(local_full), "")
            # remote saturated, local free -> no refusal either
            self.assertEqual(m._capacity_reason(remote_full), "")
            both = dict(local_full, **remote_full)
            reason = m._capacity_reason(both)
            self.assertIn("runner at cap", reason)
            self.assertIn("local", reason)
            self.assertIn("remote", reason)
        finally:
            (m.CAP, m.REMOTE_CAP, m.ratelimit_reason, m.overloaded,
             m.WAITING_KILL) = saved


class ClaimPassRemoteCapTest(unittest.TestCase):
    """claim_pass end-to-end with stubbed seams: per-class caps and
    the per-class load gate."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self.m = m
        self._saved_env = os.environ.get("JEV_LANE")
        os.environ["JEV_LANE"] = "0"
        self._saved = {k: getattr(m, k) for k in (
            "CAP", "REMOTE_CAP", "REMOTE_EXECUTORS", "MAX_LOAD_PC",
            "SCRIPT_MAX_LOAD_PC", "REMOTE_MAX_LOAD_PC",
            "RETRY_FILE", "WAITING_GATE", "DISPATCH", "OPENCODE_LANES",
            "kk_mac_servable", "dr_module", "gpu_preflight",
            "push_guard_reason", "executor_defer_reason",
            "self_stale_reason", "classify_lane", "overloaded",
            "note_defer", "start_task", "claimable", "api",
            "_note_capacity_skip", "_claim_order")}
        self._tmpdir = tempfile.TemporaryDirectory()
        m.CAP = 1
        m.REMOTE_CAP = 1
        m.REMOTE_EXECUTORS = {"jules", "nlm_batch", "kk_mac_local"}
        m.MAX_LOAD_PC = 0
        m.SCRIPT_MAX_LOAD_PC = 2.0
        m.REMOTE_MAX_LOAD_PC = 0
        m.RETRY_FILE = Path(self._tmpdir.name) / "retry-ledger.json"
        m.WAITING_GATE = "off"
        m.DISPATCH = str(SCRIPT)
        m.OPENCODE_LANES = False
        m.kk_mac_servable = lambda: False
        m.dr_module = lambda: None
        m.gpu_preflight = lambda card: ""
        m.push_guard_reason = lambda card: ""
        m.executor_defer_reason = lambda card: ""
        m.self_stale_reason = lambda: ""
        m.classify_lane = lambda card: "paid_frontier"
        m.overloaded = lambda pc=None: False
        self.posts = []
        self.defers = []
        self._cards = []
        m.note_defer = lambda card, kind, reason, **kw: \
            self.defers.append((card.get("id"), kind, reason))
        m.start_task = lambda card, typ: (f"u-{card['id']}", "", "")
        m.claimable = lambda card: (
            str((card.get("action") or {}).get("type") or "dispatch")
            if (card.get("action") or {}).get("status") == "queued"
            else "")
        m._claim_order = lambda cards: cards
        m._note_capacity_skip = lambda cap, exempt=None: None

        def fake_api(path, body=None):
            if path == "/cards":
                return {"cards": self._cards}
            self.posts.append((path, dict(body or {})))
            return {}
        m.api = fake_api
        signal.alarm(10)

    def tearDown(self):
        signal.alarm(0)
        for k, v in self._saved.items():
            setattr(self.m, k, v)
        if self._saved_env is None:
            os.environ.pop("JEV_LANE", None)
        else:
            os.environ["JEV_LANE"] = self._saved_env
        self._tmpdir.cleanup()

    def _claim_ids(self):
        return [b["id"] for p, b in self.posts
                if p == "/action" and (b or {}).get("do") == "claim"]

    def test_local_cap_full_remote_still_claims(self):
        # RUNNER_CAP=1 saturated by a local claim; the remote card must
        # still claim under RUNNER_REMOTE_CAP — the omen 3/3-jules
        # starvation this card fixes.
        st = {"local-1": {"unit": "u", "type": "dispatch",
                          "ex": ""}}
        # devin-1 first: once nlm-1 claims, BOTH classes are at cap and
        # the loop breaks — the cap note only lands for cards evaluated
        # before that point
        self._cards = [_card("devin-1"), _card("nlm-1", executor="nlm_batch")]
        self.assertTrue(self.m.claim_pass(st))
        self.assertEqual(self._claim_ids(), ["nlm-1"])
        # the local card was declined BY the local cap — noted, not
        # silently skipped
        self.assertIn(("devin-1", "cap"),
                      [(c, k) for c, k, _ in self.defers])
        self.assertTrue(any("local cap" in r for c, k, r in
                            self.defers if c == "devin-1"))

    def test_remote_cap_full_local_still_claims(self):
        st = {"r1": {"unit": "u", "type": "dispatch",
                     "ex": "nlm_batch"}}
        self._cards = [_card("nlm-2", executor="nlm_batch"),
                       _card("devin-2")]
        self.assertTrue(self.m.claim_pass(st))
        self.assertEqual(self._claim_ids(), ["devin-2"])
        self.assertIn(("nlm-2", "cap"),
                      [(c, k) for c, k, _ in self.defers])
        self.assertTrue(any("remote executor cap" in r
                            for c, k, r in self.defers
                            if c == "nlm-2"))

    def test_state_records_actual_executor(self):
        self._cards = [_card("nlm-3", executor="nlm_batch")]
        st = {}
        self.m.claim_pass(st)
        self.assertEqual(st["nlm-3"].get("ex"), "nlm_batch")

    def test_overload_still_claims_remote_not_devin(self):
        # load above every ceiling except the remote one: remote claims
        # are load-independent, heavyweight claims hold
        self.m.overloaded = lambda pc=None: pc != 0
        self._cards = [_card("nlm-4", executor="nlm_batch"),
                       _card("devin-3"),
                       _card("script-1", type="script")]
        (self._cards[2]["action"])["script"] = {"cmd": "true"}
        self.assertTrue(self.m.claim_pass({}))
        self.assertEqual(self._claim_ids(), ["nlm-4"])

    def test_overload_mid_band_claims_script_and_remote(self):
        # load between the heavy cap and the script cap: script AND
        # remote claim, heavy holds — the OPS-1182 pattern extended
        self.m.overloaded = lambda pc=None: pc is None
        self._cards = [_card("nlm-5", executor="nlm_batch"),
                       _card("devin-4"),
                       _card("script-2", type="script")]
        (self._cards[2]["action"])["script"] = {"cmd": "true"}
        self.assertTrue(self.m.claim_pass({}))
        self.assertEqual(sorted(self._claim_ids()),
                         ["nlm-5", "script-2"])

    def test_both_caps_full_skips_pass(self):
        self.m.overloaded = lambda pc=None: False
        st = {"l": {"unit": "u", "type": "dispatch", "ex": ""},
              "r": {"unit": "u", "type": "dispatch",
                    "ex": "nlm_batch"}}
        self._cards = [_card("nlm-6", executor="nlm_batch"),
                       _card("devin-5")]
        self.assertFalse(self.m.claim_pass(st))
        self.assertEqual(self._claim_ids(), [])


if __name__ == "__main__":
    unittest.main()
