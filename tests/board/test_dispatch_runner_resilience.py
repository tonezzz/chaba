"""Tests for card dispatch-runner-resilience — three runner/dispatch
guards:

  a) dispatch-wt-sweep salvage-push: a worktree holding committed-but-
     unpushed work is pushed to origin `wip/dispatch/<tid>` BEFORE the
     reaper force-removes it, the pushed ref is logged to card comms,
     and an unpushable/unproven head keeps the tree — never silently
     lost.
  b) push-credential claim gating on the kanban-dispatch claim path:
     a host that can't push ada-voice leaves the card queued (the
     runner-agent side is covered by test_runner_push_guard.py).
  c) provider rate-limit cooldown: a finished unit whose output shows
     a 429/throttle signature holds new claims on both runners
     (runner-agent finish_pass -> _capacity_reason) and the served
     dispatcher (kanban-dispatch survey -> can_claim).

No network, no systemd — git ops stay inside tmpdirs, api/systemctl are
stubbed.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
import dispatch_repos as dr  # noqa: E402


def _load(name: str, script: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "board" / script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True)


def commit(repo: Path, path: str, content: str, msg: str) -> None:
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    git(repo, "add", path)
    r = git(repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", msg)
    assert r.returncode == 0, r.stderr


TID = "20990101-000000-resilience"
BRANCH = f"dispatch/{TID}"


class SweepSalvageTest(unittest.TestCase):
    """(a) dispatch-wt-sweep must never reap unpushed commits."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("dispatch_wt_sweep", "dispatch-wt-sweep.py")

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._env = {k: os.environ.get(k)
                     for k in ("BOARD_API", "RUNNER_API")}
        os.environ["BOARD_API"] = "http://127.0.0.1:9"

        self.origin = self.tmp / "origin.git"
        self.origin.mkdir()
        r = subprocess.run(["git", "init", "-q", "--bare", "-b",
                            "master", str(self.origin)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        seed = self.tmp / "seed"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(seed)], capture_output=True)
        commit(seed, "file.txt", "base\n", "base")
        r = git(seed, "push", "-q", "-u", "origin", "master")
        assert r.returncode == 0, r.stderr

        self.repo = self.tmp / "runner-repo"
        subprocess.run(["git", "clone", "-q", str(self.origin),
                        str(self.repo)], capture_output=True)
        self.base = self.tmp / "worktrees"
        self.base.mkdir()
        self.wt = self.base / f"dispatch-wt-{TID}"
        r = git(self.repo, "worktree", "add", "-q", str(self.wt),
                "-b", BRANCH, "origin/master")
        assert r.returncode == 0, r.stderr

        self.tasks = self.tmp / "tasks"
        (self.tasks / TID).mkdir(parents=True)
        (self.tasks / TID / "meta.json").write_text(json.dumps(
            {"card": "resilience-card", "worktree": str(self.wt)}))

        # sweep's systemctl probe — the test host's real units are
        # irrelevant here
        self._saved_unit_active = self.mod.unit_active
        self._saved_note = self.mod.note_salvage
        self.mod.unit_active = lambda tid: False
        self.notes = []
        self.mod.note_salvage = lambda cid, text: \
            self.notes.append((cid, text))

    def tearDown(self):
        self.mod.unit_active = self._saved_unit_active
        self.mod.note_salvage = self._saved_note
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    def _sweep(self, apply: bool) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.mod.sweep(self.base, 0.0, self.tasks, apply)
        return buf.getvalue()

    def _wt_head(self) -> str:
        return git(self.wt, "rev-parse", "HEAD").stdout.strip()

    def test_unpushed_commits_salvaged_before_reap(self):
        commit(self.wt, "work.py", "x=1\n", "session work")
        sha = self._wt_head()
        out = self._sweep(apply=True)
        self.assertFalse(self.wt.is_dir(), out)
        # the head landed on origin under the salvage namespace
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "rev-parse",
             f"refs/heads/wip/dispatch/{TID}"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), sha)
        # and the pushed ref was logged for the card
        self.assertTrue(self.notes)
        cid, text = self.notes[0]
        self.assertEqual(cid, "resilience-card")
        self.assertIn(f"wip/dispatch/{TID}", text)
        self.assertIn(sha[:8], text)

    def test_push_failure_keeps_worktree_and_branch(self):
        commit(self.wt, "work.py", "x=1\n", "session work")
        # origin unreachable — the head can't be proven or salvaged
        git(self.repo, "remote", "set-url", "origin",
            str(self.tmp / "nonexistent.git"))
        out = self._sweep(apply=True)
        self.assertIn("KEEP", out)
        self.assertTrue(self.wt.is_dir())
        self.assertTrue((self.wt / "work.py").is_file())
        self.assertEqual(git(self.repo, "rev-parse", "--verify",
                             "--quiet", BRANCH).returncode, 0)

    def test_pushed_head_reaps_without_salvage(self):
        commit(self.wt, "work.py", "x=1\n", "session work")
        r = git(self.wt, "push", "-q", "origin", BRANCH)
        assert r.returncode == 0, r.stderr
        out = self._sweep(apply=True)
        self.assertFalse(self.wt.is_dir(), out)
        self.assertEqual(self.notes, [])
        r = subprocess.run(
            ["git", "--git-dir", str(self.origin), "rev-parse",
             "--verify", "--quiet", f"refs/heads/wip/dispatch/{TID}"],
            capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)  # no salvage ref needed

    def test_dry_run_reports_pending_salvage(self):
        commit(self.wt, "work.py", "x=1\n", "session work")
        out = self._sweep(apply=False)
        self.assertIn("would salvage-push", out)
        self.assertIn(f"wip/dispatch/{TID}", out)
        self.assertTrue(self.wt.is_dir())


class RunnerRateLimitTest(unittest.TestCase):
    """(c) runner-agent: a failed unit showing a provider 429 arms the
    claim cooldown; _capacity_reason then holds the claim pass."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("runner_agent_rl", "runner-agent.py")

    def setUp(self):
        m = self.mod
        self.m = m
        self._saved = {k: getattr(m, k) for k in (
            "STATE_DIR", "RATELIMIT_FILE", "RATELIMIT_COOLDOWN_S",
            "RETRY_FILE", "RETRY_MAX", "HOST", "CAP", "MAX_LOAD_PC",
            "WAITING_GATE")}
        self._tmpdir = tempfile.TemporaryDirectory()
        m.STATE_DIR = Path(self._tmpdir.name)
        m.RATELIMIT_FILE = m.STATE_DIR / "ratelimit.json"
        m.RETRY_FILE = m.STATE_DIR / "retry-ledger.json"
        m.RATELIMIT_COOLDOWN_S = 1800
        m.RETRY_MAX = 3
        m.HOST = "testhost"
        m.CAP = 2
        m.MAX_LOAD_PC = 0
        m.WAITING_GATE = "off"
        self.posts = []
        self._saved_api = m.api
        m.api = lambda path, body=None: (
            self.posts.append((path, body))
            or ({"cards": []} if path == "/cards" else {}))
        self._saved_collect = m.collect
        self._saved_active = m.unit_active
        self._saved_sh = m.sh
        self._saved_rt = m.task_runtime
        m.task_runtime = lambda: "systemd"
        m.sh = lambda *a, **k: _proc(rc=0, out="")

    def tearDown(self):
        m = self.m
        for k, v in self._saved.items():
            setattr(m, k, v)
        m.api = self._saved_api
        m.collect = self._saved_collect
        m.unit_active = self._saved_active
        m.sh = self._saved_sh
        m.task_runtime = self._saved_rt
        self._tmpdir.cleanup()

    def test_signature_scan(self):
        m = self.m
        for text in ("litellm.RateLimitError: 429 quota",
                     "HTTP/1.1 429 Too Many Requests",
                     "rate_limit_error: tokens/min exceeded",
                     "RESOURCE_EXHAUSTED",
                     "You exceeded your current quota",
                     "upstream throttled the request"):
            self.assertTrue(m.rate_limit_hit(text), text)
        for text in ("", "exit=0 all clean", "ran 12 tests ok",
                     "error 500 internal"):
            self.assertEqual(m.rate_limit_hit(text), "", text)

    def test_vendored_scan_matches_dispatch_repos(self):
        """runner-agent's vendored table must stay in lockstep with
        dispatch_repos.RATE_LIMIT_PAT."""
        m = self.m
        for text in ("HTTP 429", "rate_limit_error",
                     "RESOURCE_EXHAUSTED", "quota exceeded",
                     "Too Many Requests", "overloaded_error",
                     "529 provider", "throttled", "clean output", ""):
            self.assertEqual(bool(m.rate_limit_hit(text)),
                             bool(dr.rate_limit_hit(text)), text)

    def test_cooldown_gates_capacity(self):
        m = self.m
        self.assertEqual(m._capacity_reason({}), "")
        m.ratelimit_record("devin-task-x", "429")
        reason = m._capacity_reason({})
        self.assertIn("rate-limited", reason)
        # expired cooldown clears the gate
        m.RATELIMIT_FILE.write_text(json.dumps(
            {"until": time.time() - 1}))
        self.assertEqual(m._capacity_reason({}), "")

    def test_finish_pass_arms_cooldown_then_claims_hold(self):
        m = self.m
        m.collect = lambda unit: (False, "exit=1 429 rate_limit_error")
        m.unit_active = lambda unit: False
        st = {"c1": {"unit": "runner-x", "type": "script"}}
        m.finish_pass(st)
        self.assertTrue(m.RATELIMIT_FILE.exists())
        log = json.loads(m.RATELIMIT_FILE.read_text())
        self.assertGreater(log["until"], time.time())
        self.assertEqual(log["last"], "runner-x")
        # the cooldown note rode the finish comms
        note_texts = [b.get("text", "") for p, b in self.posts
                      if p == "/comment" and isinstance(b, dict)]
        self.assertTrue(any("rate-limit" in t for t in note_texts),
                        note_texts)
        # and the claim pass refuses to claim into the wall
        self.posts.clear()
        m.claimable = lambda card: "dispatch"
        m.claim_pass({})
        claims = [b for p, b in self.posts
                  if p == "/action" and (b or {}).get("do") == "claim"]
        self.assertEqual(claims, [])

    def test_clean_failure_arms_nothing(self):
        m = self.m
        m.collect = lambda unit: (False, "exit=1 syntax error near x")
        m.unit_active = lambda unit: False
        st = {"c1": {"unit": "runner-x", "type": "script"}}
        m.finish_pass(st)
        self.assertFalse(m.RATELIMIT_FILE.exists())
        self.assertEqual(m._capacity_reason({}), "")

    def test_journal_fallback_catches_signature(self):
        m = self.m
        m.sh = lambda *a, **k: _proc(
            rc=0, out="litellm proxy: 429 Too Many Requests\n")
        sig = m.rate_limit_scan("runner-x", "exit=1 (no signature here)")
        self.assertTrue(sig)

    def test_taskdir_lane_logs_catch_signature(self):
        # ADA-0242: opencode/profile runs redirect provider errors to
        # the dispatch taskdir (stderr.log/events.jsonl), not the unit
        # journal — the scan must read them before the journal fallback.
        m = self.m
        home = Path(self._tmpdir.name)
        tdir = home / ".local/share/devin-dispatch/tasks" / "t-rl"
        tdir.mkdir(parents=True)
        (tdir / "stderr.log").write_text(
            "litellm.RateLimitError: 429 "
            "free-models-per-day-high-balance\n")
        m.sh = lambda *a, **k: _proc(rc=0, out="")
        with mock.patch.object(Path, "home", return_value=home):
            sig = m.rate_limit_scan("devin-task-t-rl",
                                    "exit=1 missing_artifact")
        self.assertTrue(sig)


class KanbanDispatchGuardTest(unittest.TestCase):
    """(b)+(c) kanban-dispatch claim path: push-incapable host leaves an
    ada-voice card queued; a live rate-limit cooldown holds claims."""

    @classmethod
    def setUpClass(cls):
        cls.kd = _load("kanban_dispatch_rl", "kanban-dispatch.py")

    def setUp(self):
        kd = self.kd
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._saved = {k: getattr(kd, k) for k in (
            "CARD_DIR", "LOCK", "INDEX_FILE", "RENDER", "DISPATCH",
            "MY_LABELS", "POLICY_FILE", "HOST_CAP", "MAX_LOAD_PC",
            "WAITING_GATE", "RATELIMIT_FILE", "PUSH_GUARD")}
        self.cards = self.tmp / "cards"
        self.cards.mkdir()
        kd.CARD_DIR = self.cards
        kd.LOCK = self.tmp / "board.lock"
        kd.INDEX_FILE = self.tmp / "index.json"
        kd.RENDER = Path("/dev/null")      # `python3 /dev/null` exits 0
        kd.MY_LABELS = set()
        kd.POLICY_FILE = self.tmp / "no-policy.yml"
        kd.HOST_CAP = 9
        kd.MAX_LOAD_PC = 0
        kd.WAITING_GATE = "off"
        kd.RATELIMIT_FILE = self.tmp / "ratelimit.json"
        # dispatch launcher stub — last stdout line is the task id
        self.launcher = self.tmp / "dispatch-stub"
        self.launcher.write_text("#!/bin/sh\necho fake-task-1\n")
        self.launcher.chmod(0o755)
        kd.DISPATCH = str(self.launcher)
        # host/policy probes that must not leak into the test env
        self._saved_push_capable = kd.push_capable
        self._saved_load_policy = kd.load_policy
        self._saved_active = kd.active_tasks
        self._saved_flush = kd._flush_notify
        self._saved_preflight = kd.wc.preflight
        self._saved_fleet = kd.dr.fleet_capabilities
        kd.push_capable = lambda repo: True
        kd.load_policy = lambda: {"kill_switch": str(self.tmp / "no-kill")}
        kd.active_tasks = lambda: 0
        kd._flush_notify = lambda: None
        kd.wc.preflight = lambda card, env=None: []
        kd.dr.fleet_capabilities = lambda *a, **k: {}
        self._env = {k: os.environ.get(k) for k in
                     ("KANBAN_PRIMER", "KANBAN_PRIMER_GOOD")}
        os.environ["KANBAN_PRIMER"] = "0"
        os.environ["KANBAN_PRIMER_GOOD"] = "0"

        (self.cards / "ada-card.yml").write_text(
            "id: ada-card\ntitle: ada voice work\ncolumn: doing\n"
            "action:\n  type: dispatch\n  status: queued\n"
            "  repo: ada-voice\n")

    def tearDown(self):
        kd = self.kd
        for k, v in self._saved.items():
            setattr(kd, k, v)
        kd.push_capable = self._saved_push_capable
        kd.load_policy = self._saved_load_policy
        kd.active_tasks = self._saved_active
        kd._flush_notify = self._saved_flush
        kd.wc.preflight = self._saved_preflight
        kd.dr.fleet_capabilities = self._saved_fleet
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    def _run(self) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.kd.main()
        return buf.getvalue()

    def _card(self) -> dict:
        import yaml
        return yaml.safe_load((self.cards / "ada-card.yml").read_text())

    def test_push_incapable_host_cannot_claim(self):
        self.kd.push_capable = lambda repo: False
        out = self._run()
        card = self._card()
        self.assertIn("skipped — cannot push", out)
        self.assertEqual(card["action"]["status"], "queued")
        self.assertNotIn("task_id", card["action"])
        comms = " ".join(c.get("text", "")
                         for c in card.get("comms") or [])
        self.assertIn("push guard", comms)

    def test_push_capable_host_claims(self):
        self.kd.push_capable = lambda repo: True
        self._run()
        card = self._card()
        self.assertEqual(card["action"]["status"], "running")
        self.assertEqual(card["action"]["task_id"], "fake-task-1")

    def test_push_label_fast_path(self):
        kd = self.kd
        saved_labels = kd.MY_LABELS
        kd.MY_LABELS = {"push:ada-voice"}
        kd._PUSH_PROBE_CACHE.clear()
        saved_probe = kd.dr.push_probe
        kd.dr.push_probe = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("probe ran despite declared label"))
        try:
            self.assertTrue(kd.push_capable("ada-voice"))
        finally:
            kd.MY_LABELS = saved_labels
            kd.dr.push_probe = saved_probe

    def test_off_queue_column_card_never_claimed(self):
        """KNB-0036 follow-through: the claim queue is column-scoped —
        a stale action.status=queued on a done/review card (finish-less
        close-outs and do_move leave exactly that) is off-queue: no
        claim, no fleet-gap flag, no defer comms."""
        kd = self.kd
        for col in ("done", "review"):
            (self.cards / "ada-card.yml").write_text(
                f"id: ada-card\ntitle: ada voice work\ncolumn: {col}\n"
                "action:\n  type: dispatch\n  status: queued\n"
                "  repo: ada-voice\n")
            kd.INDEX_FILE.unlink(missing_ok=True)
            out = self._run()
            card = self._card()
            self.assertEqual(card["action"]["status"], "queued", col)
            self.assertNotIn("claimed", out)
            comms = " ".join(c.get("text", "")
                             for c in card.get("comms") or [])
            self.assertNotIn("unclaimable", comms)
            self.assertNotIn("defers", comms)

    def test_ratelimit_cooldown_defers_claims(self):
        kd = self.kd
        kd.ratelimit_record("devin-task-dead", "429")
        out = self._run()
        self.assertIn("rate-limited", out)
        card = self._card()
        self.assertEqual(card["action"]["status"], "queued")
        self.assertNotIn("task_id", card["action"])

    def test_ratelimit_scan_arms_from_journal(self):
        kd = self.kd
        saved_sh = kd.sh
        kd.sh = lambda *a, **k: _proc(
            rc=0, out="devin: provider 429 rate limit hit\n")
        try:
            kd.ratelimit_scan_task("dead-1")
        finally:
            kd.sh = saved_sh
        self.assertIn("rate-limited", kd.ratelimit_reason())

    def test_ratelimit_scan_arms_from_taskdir_logs(self):
        # opencode/profile provider errors land in the taskdir, not the
        # unit journal — the survey must scan them too.
        kd = self.kd
        home = self.tmp
        tdir = home / ".local/share/devin-dispatch/tasks" / "dead-rl"
        tdir.mkdir(parents=True)
        (tdir / "stderr.log").write_text(
            "litellm.RateLimitError: 429 quota exhausted\n")
        saved_sh = kd.sh
        kd.sh = lambda *a, **k: _proc(rc=0, out="")
        try:
            with mock.patch.object(Path, "home", return_value=home):
                kd.ratelimit_scan_task("dead-rl")
        finally:
            kd.sh = saved_sh
        self.assertIn("rate-limited", kd.ratelimit_reason())


if __name__ == "__main__":
    unittest.main()
