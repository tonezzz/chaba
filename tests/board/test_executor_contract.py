"""Tests for the explicit executor contract (card
opencode-explicit-executor-routing).

The contract: `action.executor` in {opencode, devin, script, manual} is
the card's declared executor. It is validated at the board-api door,
honored before lane classification in both claimers, persisted into the
claim body / task meta / usage.json / closeout, and — critically — a
card whose executor can't be served NEVER silently falls back to
another executor. Unset executor keeps the pre-contract classifier
fallback; unknown values fail closed.

No network, no git, no systemd — every seam is stubbed.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

os.environ["BOARD_API_COMMIT"] = "0"  # tmp card dirs aren't repo files

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))
SCRIPT = REPO / "scripts" / "board" / "runner-agent.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / "board" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _card(**action_kw):
    a = {"type": "dispatch", "status": "queued", "repo": "chaba"}
    a.update(action_kw)
    return {"id": "ex-card", "title": "executor test", "spec": "do a thing",
            "action": a}


def _write_card(d: Path, cid: str, **fields) -> Path:
    import yaml
    card = {"id": cid}
    card.update(fields)
    p = d / f"{cid}.yml"
    p.write_text(__import__("yaml").safe_dump(card, sort_keys=False))
    return p


# ------------------------------------------------------------ claimable

class ClaimableContractTest(unittest.TestCase):
    """runner-agent.claimable + executor_defer_reason."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("runner-agent.py")

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in
                       ("OPENCODE_LANES", "DISPATCH", "LABELS", "HOST")}
        self._saved_fn = {k: getattr(m, k) for k in
                          ("opencode_bin", "push_capable", "shutil_which")}
        m.DISPATCH = str(SCRIPT)          # dispatch executor present
        m.push_capable = lambda repo: True
        m.shutil_which = lambda name: True
        m.HOST = "testhost"
        m.LABELS = set()

    def tearDown(self):
        m = self.mod
        for k, v in {**self._saved, **self._saved_fn}.items():
            setattr(m, k, v)

    def test_manual_executor_never_claimed(self):
        self.assertEqual(self.mod.claimable(_card(executor="manual")), "")

    def test_unknown_executor_fails_closed(self):
        self.assertEqual(self.mod.claimable(_card(executor="gandalf")), "")
        # and the defer note explains why instead of silent starvation
        r = self.mod.executor_defer_reason(_card(executor="gandalf"))
        self.assertIn("not a known executor", r)
        self.assertIn("fail closed", r)

    def test_opencode_executor_claimable_when_capable(self):
        self.mod.OPENCODE_LANES = True
        self.mod.opencode_bin = lambda: "/home/x/.opencode/bin/opencode"
        c = _card(executor="opencode", agent_profile="ops-readonly")
        self.assertEqual(self.mod.claimable(c), "dispatch")

    def test_opencode_executor_deferred_when_lanes_off(self):
        """The core no-silent-fallback case: OPENCODE_LANES=0 leaves the
        card queued for a capable host — never a devin claim."""
        self.mod.OPENCODE_LANES = False
        self.mod.opencode_bin = lambda: "/x/opencode"
        c = _card(executor="opencode", agent_profile="ops-readonly")
        self.assertEqual(self.mod.claimable(c), "")
        r = self.mod.executor_defer_reason(c)
        self.assertIn("OPENCODE_LANES=0", r)
        self.assertIn("never silently fall back", r)

    def test_opencode_executor_deferred_without_binary(self):
        self.mod.OPENCODE_LANES = True
        self.mod.opencode_bin = lambda: ""
        c = _card(executor="opencode")
        self.assertEqual(self.mod.claimable(c), "")
        self.assertIn("no opencode binary",
                      self.mod.executor_defer_reason(c))

    def test_opencode_executor_needs_push_too(self):
        self.mod.OPENCODE_LANES = True
        self.mod.opencode_bin = lambda: "/x/opencode"
        self.mod.push_capable = lambda repo: False
        self.assertEqual(
            self.mod.claimable(_card(executor="opencode")), "")

    def test_devin_executor_claimable(self):
        self.assertEqual(
            self.mod.claimable(_card(executor="devin")), "dispatch")

    def test_script_executor_routes_to_script_block(self):
        c = _card(executor="script",
                  script={"cmd": "make check", "repo": "chaba"})
        self.assertEqual(self.mod.claimable(c), "script")
        # without the script block the contract can't be served
        self.assertEqual(self.mod.claimable(_card(executor="script")), "")

    def test_no_executor_preserves_fallback(self):
        """Unset executor = pre-contract claimability unchanged."""
        self.assertEqual(self.mod.claimable(_card()), "dispatch")

    def test_target_host_pin(self):
        c = _card(executor="devin", target_host="otherhost")
        self.assertEqual(self.mod.claimable(c), "")
        c2 = _card(executor="devin", target_host="testhost")
        self.assertEqual(self.mod.claimable(c2), "dispatch")

    def test_executor_on_non_dispatch_type_fails_closed(self):
        """executor=opencode on a script-typed card is a contradictory
        contract — not claimed rather than improvising a route."""
        c = _card(executor="opencode")
        c["action"]["type"] = "script"
        c["action"]["script"] = {"cmd": "x", "repo": "chaba"}
        self.assertEqual(self.mod.claimable(c), "")


# ------------------------------------------------------------- routing

class StartTaskContractTest(unittest.TestCase):
    """runner-agent.start_task honors the declared executor."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("runner-agent.py")

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in
                       ("OPENCODE_LANES", "DISPATCH", "HOST")}
        self._saved_fn = {k: getattr(m, k) for k in
                          ("sh", "classify_lane", "start_opencode_lane",
                           "dr_module", "enforce_task_limits")}
        m.DISPATCH = str(SCRIPT)
        m.dr_module = lambda: None
        m.enforce_task_limits = lambda *a, **k: None
        self.calls = []
        m.sh = lambda argv, **kw: self.calls.append(argv) or _proc(
            0, "fake-tid-123\n")

    def tearDown(self):
        m = self.mod
        for k, v in {**self._saved, **self._saved_fn}.items():
            setattr(m, k, v)

    def test_explicit_opencode_routes_to_lane(self):
        seen = []
        self.mod.start_opencode_lane = lambda card, lane, unit: (
            seen.append((lane, unit)) or ("devin-task-x", "x", ""))
        unit, tid, err = self.mod.start_task(
            _card(executor="opencode", agent_profile="ops-readonly"),
            "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(unit, "devin-task-x")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "")  # executor route, not a lane
        self.assertFalse(self.calls)      # no devin-dispatch spawn

    def test_opencode_start_failure_never_falls_back(self):
        """A failing OpenCode start fails the task — devin is never
        tried (this is the contract's central guarantee)."""
        self.mod.start_opencode_lane = lambda *a: (
            "", "", "opencode is not installed on this runner")
        unit, tid, err = self.mod.start_task(
            _card(executor="opencode"), "dispatch")
        self.assertEqual(unit, "")
        self.assertIn("not installed", err)
        self.assertFalse(self.calls)

    def test_explicit_devin_stays_devin_even_with_lane(self):
        """executor=devin wins over lane routing — no classify, no
        opencode detour, plain devin-dispatch argv."""
        self.mod.OPENCODE_LANES = True
        oc_calls = []
        self.mod.start_opencode_lane = lambda *a: (
            oc_calls.append(a) or ("u", "t", ""))
        cls = []
        self.mod.classify_lane = lambda card: (
            cls.append(card) or "free_lane")
        unit, tid, err = self.mod.start_task(
            _card(executor="devin", lane="free_lane",
                  agent_profile="ops-readonly"), "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(unit, "devin-task-fake-tid-123")
        self.assertFalse(oc_calls)   # lane+profile can't steal it
        self.assertFalse(cls)        # classifier never consulted
        self.assertTrue(self.calls)  # devin-dispatch spawn happened
        self.assertEqual(self.calls[0][0], str(SCRIPT))

    def test_manual_and_unknown_fail_closed(self):
        for ex in ("manual", "gandalf"):
            unit, tid, err = self.mod.start_task(
                _card(executor=ex), "dispatch")
            self.assertEqual(unit, "")
            self.assertIn("fail closed", err)
            self.assertFalse(self.calls)

    def test_no_executor_classifier_fallback(self):
        """No executor -> the old safe fallback: classifier decides."""
        self.mod.OPENCODE_LANES = False
        self.mod.classify_lane = lambda card: "paid_frontier"
        card = _card()
        unit, tid, err = self.mod.start_task(card, "dispatch")
        self.assertEqual(err, "")
        self.assertEqual(card["action"]["lane"], "paid_frontier")
        self.assertEqual(unit, "devin-task-fake-tid-123")


# ------------------------------------------------------------ finish

class FinishOpenCodeLaneTest(unittest.TestCase):
    """finish_opencode_lane: declared artifact must land + verifier pass
    before the merge gate runs; contract failures hold the merge."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("runner-agent.py")

    def setUp(self):
        m = self.mod
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self._home_old = os.environ.get("HOME")
        os.environ["HOME"] = self.td.name
        self.addCleanup(self._restore_home)
        self._ocp = m.oc_profiles_module
        self.tid = "20260101-000000-t"
        self.taskdir = (Path(self.td.name) / ".local/share/devin-dispatch"
                        "/tasks" / self.tid)
        self.taskdir.mkdir(parents=True)
        self.wt = Path(self.td.name) / "wt"
        self.wt.mkdir()
        self.vdir = Path(self.td.name) / "verifiers"
        self.vdir.mkdir()

    def _restore_home(self):
        if self._home_old is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._home_old

    def tearDown(self):
        self.mod.oc_profiles_module = self._ocp

    def _meta(self, executor="opencode:ops-readonly"):
        (self.taskdir / "meta.json").write_text(json.dumps({
            "executor": executor, "profile": "ops-readonly",
            "model": "litellm/gemini-3.5-flash-lite",
            "provider": "litellm", "worktree": str(self.wt),
            "repo_root": str(self.td.name)}))

    def _events(self, text):
        ev = {"part": {"type": "text", "text": text}}
        (self.taskdir / "events.jsonl").write_text(
            json.dumps(ev) + "\n")
        (self.taskdir / "exit_code").write_text("0\n")

    def _fake_ocp(self, prof=None):
        prof = prof or {"id": "ops-readonly",
                        "artifact": {"mode": "message", "format": "json",
                                     "dirs": ["evals/out/"]},
                        "verifier": {"ref": "verifiers/v.py"},
                        "mcp": {"allowed": []}}
        return types.SimpleNamespace(
            load_profile=lambda pid: prof,
            audit_events=lambda *a: {
                "tokens": {"input": 10, "output": 5, "cache_read": 0,
                           "cache_write": 0},
                "tool_calls": ["read"], "denials": [],
                "mutating_commands": [], "verifier_peeks": [],
                "write_attempts": []},
            final_text=lambda p: json.loads(
                Path(p).read_text().splitlines()[-1])["part"]["text"],
            extract_artifact=lambda text, fmt: text if text else None,
            agent_name=lambda pid: f"task-{pid}",
            lane_gate=None)

    def _card_artifact(self, path="evals/out/report.json"):
        return _card(executor="opencode", artifact=path)

    def test_not_opencode_task_is_noop(self):
        self._meta(executor="devin")
        may, notes = self.mod.finish_opencode_lane(
            "c1", {"tid": self.tid}, self._card_artifact())
        self.assertTrue(may)
        self.assertEqual(notes, [])

    def test_artifact_lands_and_verifier_passes(self):
        self._meta()
        self._events('{"host": "h1"}')
        (self.vdir / "v.py").write_text(
            "def verify(rd): return {'verdict': 'pass', 'checks': {}}\n")
        self.mod.oc_profiles_module = lambda: self._fake_ocp()
        card = self._card_artifact()
        may, notes = self.mod.finish_opencode_lane(
            card["id"], {"tid": self.tid}, card)
        self.assertTrue(may)
        self.assertIn("artifact landed", " ".join(notes))
        # durable proof: worktree file + taskdir artifact.out + verdict
        self.assertTrue((self.wt / "evals/out/report.json").is_file())
        self.assertTrue((self.taskdir / "artifact.out").is_file())
        self.assertTrue((self.taskdir / "verdict.json").is_file())
        usage = json.loads((self.taskdir / "usage.json").read_text())
        self.assertEqual(usage["verdict"], "pass")
        self.assertTrue(usage["artifact_landed"])
        self.assertEqual(usage["exit_code"], 0)

    def test_missing_artifact_holds_merge(self):
        self._meta()
        self._events("")  # agent emitted nothing
        self.mod.oc_profiles_module = lambda: self._fake_ocp()
        may, notes = self.mod.finish_opencode_lane(
            "c1", {"tid": self.tid}, self._card_artifact())
        self.assertFalse(may)
        self.assertIn("merge held", " ".join(notes))
        usage = json.loads((self.taskdir / "usage.json").read_text())
        self.assertEqual(usage["verdict"], "fail")
        self.assertFalse(usage["artifact_landed"])

    def test_verifier_fail_holds_merge(self):
        self._meta()
        self._events('{"host": "h1"}')
        (self.vdir / "v.py").write_text(
            "def verify(rd): return {'verdict': 'fail', "
            "'checks': {'facts match': False}}\n")
        self.mod.oc_profiles_module = lambda: self._fake_ocp()
        may, notes = self.mod.finish_opencode_lane(
            "c1", {"tid": self.tid}, self._card_artifact())
        self.assertFalse(may)
        self.assertIn("opencode verifier: fail", " ".join(notes))
        # the artifact still landed for inspection — the merge is held
        self.assertTrue((self.wt / "evals/out/report.json").is_file())

    def test_artifact_outside_profile_dirs_holds_merge(self):
        self._meta()
        self._events('{"x": 1}')
        self.mod.oc_profiles_module = lambda: self._fake_ocp()
        may, notes = self.mod.finish_opencode_lane(
            "c1", {"tid": self.tid},
            self._card_artifact(path="src/evil.py"))
        self.assertFalse(may)
        self.assertIn("outside profile dirs", " ".join(notes))

    def test_denials_fail_the_closeout(self):
        """A verifier pass with denied tool calls is still a contract
        violation — the merge holds."""
        self._meta()
        self._events('{"x": 1}')
        (self.vdir / "v.py").write_text(
            "def verify(rd): return {'verdict': 'pass', 'checks': {}}\n")
        fake = self._fake_ocp()
        a = fake.audit_events("x")
        a["denials"] = ["write:/etc/passwd"]
        fake = types.SimpleNamespace(**{**fake.__dict__,
                                        "audit_events": lambda *x: a})
        self.mod.oc_profiles_module = lambda: fake
        may, notes = self.mod.finish_opencode_lane(
            "c1", {"tid": self.tid}, self._card_artifact())
        self.assertFalse(may)

    def test_no_declared_artifact_still_enriches_usage(self):
        self._meta()
        self._events('{"x": 1}')
        self.mod.oc_profiles_module = lambda: self._fake_ocp()
        may, notes = self.mod.finish_opencode_lane(
            "c1", {"tid": self.tid}, _card(executor="opencode"))
        self.assertTrue(may)
        self.assertIn("no action.artifact", " ".join(notes))
        usage = json.loads((self.taskdir / "usage.json").read_text())
        self.assertEqual(usage["tool_calls"], 1)


# -------------------------------------------------------------- board

class BoardApiContractTest(unittest.TestCase):
    """board-api preserves + validates the executor fields."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("board-api.py")

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.mod.CARD_DIR = Path(self.td.name)

    def rejects(self, body, frag):
        try:
            self.mod.do_create(body, "devin")
        except ValueError as e:
            self.assertIn(frag, str(e))
            return
        raise AssertionError(f"expected ValueError containing {frag!r}")

    def test_create_preserves_executor_fields(self):
        res = self.mod.do_create(
            {"id": "c-oc", "title": "t",
             "action": {"type": "dispatch", "executor": "opencode",
                        "agent_profile": "ops-readonly",
                        "model": "litellm/gemini-3.5-flash-lite",
                        "target_host": "idc02"},
             "queue": True}, "devin")
        import yaml
        saved = yaml.safe_load((Path(self.td.name) / "c-oc.yml")
                               .read_text())
        a = saved["action"]
        self.assertEqual(a["executor"], "opencode")
        self.assertEqual(a["agent_profile"], "ops-readonly")
        self.assertEqual(a["target_host"], "idc02")
        self.assertEqual(a["model"], "litellm/gemini-3.5-flash-lite")

    def test_create_validates_executor(self):
        self.rejects({"id": "c-bad", "title": "t",
                      "action": {"type": "dispatch",
                                 "executor": "gandalf"}},
                     "action.executor must be one of")

    def test_create_validates_profile_and_host(self):
        self.rejects({"id": "c-bad", "title": "t",
                      "action": {"type": "dispatch",
                                 "executor": "opencode",
                                 "agent_profile": "Bad_Prof!"}},
                     "action.agent_profile")
        self.rejects({"id": "c-bad", "title": "t",
                      "action": {"type": "dispatch",
                                 "target_host": "bad host;rm"}},
                     "action.target_host")

    def test_create_model_accepts_provider_ids(self):
        self.mod.do_create(
            {"id": "c-mod", "title": "t",
             "action": {"type": "dispatch",
                        "model": "litellm/or-claude-fable-5.1"}}, "devin")
        self.rejects({"id": "c-bad", "title": "t",
                      "action": {"type": "dispatch",
                                 "model": "x; rm -rf /"}},
                     "action.model")

    def test_queue_warns_manual_executor(self):
        card = {"id": "c-em", "column": "backlog",
                "action": {"type": "dispatch", "executor": "manual"}}
        msg = self.mod.do_action(card, "queue", "tony")
        self.assertIn("executor=manual", msg)
        self.assertIn("starve", msg)

    def test_claim_persists_executor_fields(self):
        card = {"id": "c-claim",
                "action": {"type": "dispatch", "status": "queued"}}
        self.mod.do_claim(card,
                          {"host": "h1", "executor": "opencode",
                           "agent_profile": "ops-readonly",
                           "target_host": "h1"})
        a = card["action"]
        self.assertEqual(a["executor"], "opencode")
        self.assertEqual(a["agent_profile"], "ops-readonly")
        self.assertEqual(a["target_host"], "h1")

    def test_claim_refuses_executor_change(self):
        card = {"id": "c-lock",
                "action": {"type": "dispatch", "status": "queued",
                           "executor": "opencode"}}
        try:
            self.mod.do_claim(card, {"host": "h1", "executor": "devin"})
        except ValueError as e:
            self.assertIn("can't change the contract", str(e))
            return
        raise AssertionError("expected ValueError")

    def test_claim_rejects_bad_executor(self):
        card = {"id": "c-bex",
                "action": {"type": "dispatch", "status": "queued"}}
        try:
            self.mod.do_claim(card, {"host": "h1", "executor": "gandalf"})
        except ValueError as e:
            self.assertIn("invalid action executor", str(e))
            return
        raise AssertionError("expected ValueError")


# ------------------------------------------------------- kanban-dispatch

class KanbanDispatchContractTest(unittest.TestCase):
    """kanban-dispatch's only executor is devin — declared non-devin
    executors are skipped with a reason, never silently run."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("kanban-dispatch.py")

    def _run(self, *cards):
        m = self.mod
        with tempfile.TemporaryDirectory() as td:
            m.CARD_DIR = Path(td)
            m.LOCK = Path(td) / "lock"
            for cid, fields in cards:
                _write_card(Path(td), cid, **fields)
            saved = (m.load_policy, m.overloaded, m.active_tasks,
                     m.push_capable, m.start_pending)
            self.started = []
            m.load_policy = lambda: {"kill_switch": str(Path(td) / "k")}
            m.overloaded = lambda: False
            m.active_tasks = lambda: 0
            m.push_capable = lambda repo: True
            m.start_pending = lambda p: (self.started.append(p.stem)
                                         or "started")
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    m.main()
            finally:
                (m.load_policy, m.overloaded, m.active_tasks,
                 m.push_capable, m.start_pending) = saved
            return buf.getvalue()

    def test_opencode_executor_skipped(self):
        out = self._run(("c-oc", {"action": {"status": "queued",
                                            "executor": "opencode"}}))
        self.assertIn("skipped — executor=opencode", out)
        self.assertEqual(self.started, [])

    def test_manual_and_unknown_skipped(self):
        out = self._run(
            ("c-man", {"action": {"status": "queued",
                                  "executor": "manual"}}),
            ("c-bog", {"action": {"status": "queued",
                                  "executor": "gandalf"}}))
        self.assertIn("executor=manual", out)
        self.assertIn("Tony's hands", out)
        self.assertIn("not a known executor", out)
        self.assertEqual(self.started, [])

    def test_devin_executor_claimed(self):
        out = self._run(("c-dev", {"action": {"status": "queued",
                                             "executor": "devin"}}))
        self.assertNotIn("skipped", out)
        self.assertEqual(self.started, ["c-dev"])

    def test_target_host_mismatch_skipped(self):
        out = self._run(("c-pin", {"action": {"status": "queued",
                                             "target_host": "idc99"}}))
        self.assertIn("target_host=idc99", out)
        self.assertEqual(self.started, [])

    def test_no_executor_still_claims(self):
        out = self._run(("c-plain", {"action": {"status": "queued"}}))
        self.assertEqual(self.started, ["c-plain"])

    def test_start_pending_executor_env(self):
        """start_pending passes the contract to devin-dispatch via
        DISPATCH_* env so _meta_write can stamp meta+usage."""
        m = self.mod
        with tempfile.TemporaryDirectory() as td:
            m.CARD_DIR = Path(td)
            m.LOCK = Path(td) / "lock"
            _write_card(Path(td), "c-env",
                        action={"status": "starting", "executor": "devin",
                                "model": "swe-2-high",
                                "target_host": "idc02"})
            calls = []
            saved = (m.sh, m.DISPATCH)
            m.sh = lambda argv, **kw: (
                calls.append(kw.get("env") or {})
                or _proc(0, "tid-env-1\n"))
            try:
                m.start_pending(Path(td) / "c-env.yml")
            finally:
                (m.sh, m.DISPATCH) = saved
            self.assertTrue(calls)
            env = calls[0]
            self.assertEqual(env["DISPATCH_EXECUTOR"], "devin")
            self.assertEqual(env["DISPATCH_CARD"], "c-env")
            self.assertEqual(env["DISPATCH_PROVIDER"], "devin")
            self.assertEqual(env["DISPATCH_TARGET_HOST"], "idc02")


# ---------------------------------------------------------- shared helpers

class DispatchReposContractTest(unittest.TestCase):
    """dispatch_repos contract helpers + closeout executor fields."""

    @classmethod
    def setUpClass(cls):
        import dispatch_repos as dr
        cls.dr = dr

    def test_helpers(self):
        dr = self.dr
        c = _card(executor="opencode", agent_profile="ops-readonly",
                  model="litellm/g-3.5", target_host="idc02")
        self.assertEqual(dr.card_executor(c), "opencode")
        self.assertEqual(dr.card_profile(c), "ops-readonly")
        self.assertEqual(dr.card_target_host(c), "idc02")
        self.assertEqual(dr.model_provider("litellm/g-3.5"), "litellm")
        self.assertEqual(dr.model_provider("swe-2-high"), "devin")
        self.assertEqual(dr.model_provider(""), "")
        b = dr.executor_blurb(c)
        for frag in ("executor=opencode", "provider=litellm",
                     "model=litellm/g-3.5", "profile=ops-readonly"):
            self.assertIn(frag, b)
        # pre-contract alias still resolves
        c2 = _card(profile="branch-code")
        self.assertEqual(dr.card_profile(c2), "branch-code")
        self.assertEqual(dr.card_executor(_card()), "")

    def test_closeout_notes_executor_line(self):
        res = {"merged": True, "merged_sha": "abc",
               "session": {"executor": "opencode:ops-readonly",
                           "provider": "litellm",
                           "model": "litellm/g-3.5",
                           "profile": "ops-readonly"}}
        notes = self.dr.close_out_notes(res)
        self.assertTrue(any("executor=opencode" in n for n in notes))
        self.assertTrue(any("provider=litellm" in n for n in notes))

    def test_regexes(self):
        dr = self.dr
        for good in ("litellm/g-3.5", "swe-2-high", "or.claude_5.1"):
            self.assertTrue(dr.MODEL_ID_RE.match(good), good)
        for bad in ("x; rm -rf /", "sp ace", "", "x" * 81):
            self.assertFalse(dr.MODEL_ID_RE.match(bad), bad)
        for good in ("ops-readonly", "branch-code"):
            self.assertTrue(dr.PROFILE_ID_RE.match(good))
        for bad in ("Bad", "x_y", "-x", "x" * 62):
            self.assertFalse(dr.PROFILE_ID_RE.match(bad), bad)
        for good in ("idc02", "tony-dell.ts.net"):
            self.assertTrue(dr.HOST_ID_RE.match(good))
        for bad in ("bad host", "-x", "x" * 64):
            self.assertFalse(dr.HOST_ID_RE.match(bad), bad)


if __name__ == "__main__":
    unittest.main()
