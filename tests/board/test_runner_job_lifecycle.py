"""ADA-0024 — dispatch job-lifecycle parity in runner-agent.

A dispatch task that stops to ask Tony is a BLOCKED job, not a failed
one: it must land a job/<id> doc in the shared devin-handoff bank, raise
a board ask carrying the question, and stay claimed until an answer
arrives. It must never go through do_finish(ok=False) — that burns the
retry ledger and auto-requeues a job whose only problem is a missing
human answer (the Devin error-handling standard: blocked != failed).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent_job_life",
                                                  SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    status = 200

    def __init__(self, payload=None):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class JobLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self.m = m
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._home = mock.patch.object(m.Path, "home",
                                       return_value=self.root)
        self._home.start()
        self._real_ledger = m.job_ledger_write
        self.saved = {k: getattr(m, k) for k in (
            "HOST", "JOB_LIFECYCLE_ON", "DISPATCH_JOB_MDDB",
            "DISPATCH_JOB_COLLECTION")}
        m.HOST = "testhost"
        m.JOB_LIFECYCLE_ON = True
        m.DISPATCH_JOB_MDDB = "http://mddb.test/v1"
        m.DISPATCH_JOB_COLLECTION = "ada-ha-bank-devin-handoff"
        self.posts = []
        self.writes = []
        self.notifies = []
        self._api = mock.patch.object(
            m, "api", side_effect=lambda p, b=None: (
                self.posts.append((p, b)) or {}))
        self._api.start()
        self._ledger = mock.patch.object(
            m, "job_ledger_write",
            side_effect=lambda *a, **k: (
                self.writes.append((a, k)) or True))
        self._ledger.start()
        self._notify = mock.patch.object(
            m, "_notify", side_effect=lambda *a: self.notifies.append(a))
        self._notify.start()

    def tearDown(self):
        self._notify.stop()
        self._ledger.stop()
        self._api.stop()
        self._home.stop()
        for k, v in self.saved.items():
            setattr(self.m, k, v)
        self.tmp.cleanup()

    def taskdir(self, tid="card-1-1000") -> Path:
        d = (self.root / ".local/share/devin-dispatch/tasks" / tid)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- needs-input detection ---------------------------------------

    def test_marker_first_line_wins(self):
        td = self.taskdir()
        (td / "needs-input.txt").write_text(
            "Which DVR is the target?\nsome context\nmore\n")
        (td / "exit_code").write_text("42\n")
        q = self.m.needs_input_question({"tid": td.name})
        self.assertEqual(q, "Which DVR is the target?")

    def test_needs_input_line_from_events_is_persisted(self):
        td = self.taskdir()
        (td / "events.jsonl").write_text(
            '{"type":"text","text":"working"}\n'
            '{"text":"NEEDS-INPUT: pick the host for the report"}\n'
            '{"text":"NEEDS-INPUT: newer question wins"}\n')
        q = self.m.needs_input_question({"tid": td.name})
        self.assertEqual(q, "newer question wins")
        self.assertEqual((td / "needs-input.txt").read_text(),
                         "newer question wins\n")

    def test_exit42_without_marker_is_generic_ask(self):
        td = self.taskdir()
        (td / "exit_code").write_text("42\n")
        self.assertIn("direction", self.m.needs_input_question(
            {"tid": td.name}))

    def test_ordinary_failure_is_not_needs_input(self):
        td = self.taskdir()
        (td / "exit_code").write_text("1\n")
        (td / "events.jsonl").write_text(
            '{"text":"Traceback: something broke"}\n')
        self.assertEqual(self.m.needs_input_question({"tid": td.name}), "")

    # --- ledger payload + write --------------------------------------

    def test_job_doc_shape_matches_job_run(self):
        doc = self.m._job_doc("card-1", "awaiting-user",
                              question="Pick a host", detail="trace")
        self.assertEqual(doc["collection"],
                         "ada-ha-bank-devin-handoff")
        self.assertEqual(doc["key"], "job/card-1")
        self.assertEqual(doc["meta"]["kind"], ["job"])
        self.assertEqual(doc["meta"]["status"], ["awaiting-user"])
        self.assertEqual(doc["meta"]["question"], ["Pick a host"])
        # every meta value is a list — bank schema, per job-run.sh
        self.assertTrue(all(isinstance(v, list)
                            for v in doc["meta"].values()))
        self.assertIn("Needs input: Pick a host", doc["contentMd"])

    def test_ledger_write_posts_add(self):
        with mock.patch.object(self.m.urllib.request, "urlopen",
                               return_value=_Resp()) as up:
            ok = self._real_ledger("card-1", "running")
        self.assertTrue(ok)
        req = up.call_args.args[0]
        self.assertEqual(req.full_url, "http://mddb.test/v1/add")
        self.assertEqual(json.loads(req.data)["key"], "job/card-1")

    def test_ledger_disabled_is_a_noop(self):
        self.m.JOB_LIFECYCLE_ON = False
        with mock.patch.object(self.m.urllib.request, "urlopen") as up:
            self.assertFalse(self._real_ledger("card-1", "running"))
        up.assert_not_called()

    # --- answer consumption ------------------------------------------

    def test_last_answer_prefers_answer_kind(self):
        td = self.taskdir()
        (td / "answers.jsonl").write_text("\n".join([
            json.dumps({"kind": "comment", "answer": "just chatting"}),
            json.dumps({"kind": "answer", "answer": "use idc02"}),
        ]) + "\n")
        self.assertEqual(self.m._last_answer({"tid": td.name}), "use idc02")

    def test_request_answer_from_card(self):
        card = self._card()
        card["requests"] = [
            {"id": "job-input-card-1", "status": "open", "ask": "host?"},
            {"id": "job-input-card-1", "status": "answered",
             "answer": "use mn01"},
        ]
        self.assertEqual(self.m._request_answer(card, "card-1"), "use mn01")

    def test_mddb_answer_doc(self):
        doc = {"key": "answer/card-1",
               "contentMd": "Answer for job card-1 (2026-11-24T00:00:00Z):"
                            "\n\nuse idc03"}
        with mock.patch.object(self.m.urllib.request, "urlopen",
                               return_value=_Resp(doc)) as up:
            answer = self.m._mddb_answer("card-1")
        self.assertEqual(answer, "use idc03")
        req = up.call_args.args[0]
        self.assertEqual(req.full_url, "http://mddb.test/v1/get")
        self.assertEqual(json.loads(req.data)["key"], "answer/card-1")

    # --- finish-pass integration -------------------------------------

    def _card(self, status="running"):
        return {"id": "card-1", "title": "card-1",
                "action": {"type": "dispatch", "status": status},
                "comms": []}

    def test_enter_awaiting_has_no_finish_post(self):
        ent = {"tid": "card-1-1000", "unit": "devin-task-card-1-1000",
               "type": "dispatch"}
        self.m._enter_awaiting("card-1", ent, "Which host?")
        self.assertIn("job_awaiting", ent)
        self.assertFalse([p for p, _ in self.posts if p == "/action"])
        self.assertTrue([b for p, b in self.posts
                         if p == "/request" and b.get("ask")])
        self.assertTrue([b for p, b in self.posts
                         if p == "/comment" and b.get("awaiting_action")])
        self.assertEqual(self.writes[0][0], ("card-1", "awaiting-user"))
        self.assertTrue(self.notifies)

    def test_finish_pass_parks_needs_input(self):
        td = self.taskdir()
        (td / "needs-input.txt").write_text("Which DVR?\n")
        (td / "exit_code").write_text("42\n")
        ent = {"type": "dispatch", "unit": "devin-task-card-1-1000",
               "tid": td.name}
        with mock.patch.object(self.m, "unit_active", return_value=False), \
             mock.patch.object(self.m, "collect",
                               return_value=(False, "exit 42")):
            changed = self.m.finish_pass({"card-1": ent})
        self.assertTrue(changed)
        self.assertIn("job_awaiting", ent)
        self.assertEqual(ent["job_awaiting"]["question"], "Which DVR?")
        self.assertFalse([p for p, _ in self.posts if p == "/action"])

    def test_finish_pass_resumes_on_answer(self):
        td = self.taskdir()
        (td / "answers.jsonl").write_text(json.dumps({
            "kind": "answer", "answer": "use idc02"}) + "\n")
        ent = {"type": "dispatch", "unit": "devin-task-card-1-1000",
               "tid": td.name,
               "job_awaiting": {"question": "Which host?", "at": "now"}}
        with mock.patch.object(self.m, "api",
                               side_effect=lambda p, b=None: (
                                   self.posts.append((p, b)) or
                                   ({"cards": [self._card()]}
                                    if p == "/cards" else {}))), \
             mock.patch.object(self.m, "start_task",
                               return_value=("devin-task-card-1-1000-fu1",
                                             "card-1-1000-fu1", "")) as st:
            changed = self.m.finish_pass({"card-1": ent})
        self.assertTrue(changed)
        st.assert_called_once()
        self.assertNotIn("job_awaiting", ent)
        self.assertEqual(ent["unit"], "devin-task-card-1-1000-fu1")
        self.assertEqual(self.writes[0][0], ("card-1", "answered"))
        carried = (self.root / ".local/share/devin-dispatch/tasks"
                   / "card-1-1000-fu1" / "answers.jsonl").read_text()
        self.assertIn("use idc02", carried)

    def test_normal_finish_closes_ledger(self):
        ent = {"type": "dispatch", "unit": "devin-task-card-1-1000",
               "tid": "card-1-1000"}
        with mock.patch.object(self.m, "unit_active", return_value=False), \
             mock.patch.object(self.m, "collect",
                               return_value=(True, "artifact landed")), \
             mock.patch.object(self.m, "finish_opencode_lane",
                               return_value=(True, [])), \
             mock.patch.object(self.m, "finish_kk_mac_lane",
                               return_value=(True, [], "")), \
             mock.patch.object(self.m, "finish_nlm_lane",
                               return_value=(True, [])), \
             mock.patch.object(self.m, "close_out_merge",
                               return_value=(True, [])):
            self.m.finish_pass({"card-1": ent})
        self.assertIn(("card-1", "done"), [w[0] for w in self.writes])
        self.assertTrue([p for p, _ in self.posts if p == "/action"])

    def test_failed_resume_does_not_retry_every_pass(self):
        td = self.taskdir()
        card = self._card()
        card["requests"] = [{"id": "job-input-card-1",
                             "status": "answered", "answer": "go"}]
        ent = {"type": "dispatch", "unit": "devin-task-card-1-1000",
               "tid": td.name,
               "job_awaiting": {"question": "ok?", "at": "now"}}
        with mock.patch.object(self.m, "api",
                               side_effect=lambda p, b=None: (
                                   {"cards": [card]} if p == "/cards"
                                   else {})), \
             mock.patch.object(self.m, "start_task",
                               return_value=("", "", "unit boom")) as st:
            self.m.finish_pass({"card-1": ent})
            self.m.finish_pass({"card-1": ent})
        st.assert_called_once()  # first pass only — then held for a human
        self.assertTrue(ent["job_awaiting"]["resume_failed"])
        self.assertFalse([p for p, _ in self.posts if p == "/action"])


if __name__ == "__main__":
    unittest.main()
