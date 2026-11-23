"""Tests for devin-dispatch-tg-watch — the TG lane over the MDDB
dispatch job ledger (job/* + answer/* docs in ada-ha-bank-devin-handoff).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ops/devin-dispatch-tg-watch.py"

spec = importlib.util.spec_from_file_location("devin_dispatch_tg_watch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["devin_dispatch_tg_watch"] = mod
spec.loader.exec_module(mod)

NOW = datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def doc(key: str, status: str, content: str, *,
        kind: str = "job", host: str = "tony-dell",
        ts: datetime | None = None, question: str = "") -> dict:
    jid = key.split("/", 1)[-1]
    meta = {
        "kind": [kind], "status": [status], "job_id": [jid],
        "host": [host], "ts": [iso(ts or NOW)],
        "source": ["devin-dispatch"], "written_by": ["devin-dispatch"],
    }
    if question:
        meta["question"] = [question]
    return {"key": key, "contentMd": content, "meta": meta}


def job_doc(jid: str, status: str, summary: str = "",
            ts: datetime | None = None, **kw) -> dict:
    question = kw.pop("question", "")
    content = f"Job {jid} on tony-dell: {status}."
    if question:
        content += f"\n\nNeeds input: {question}"
    if summary:
        content += f"\n\n{summary}"
    return doc(f"job/{jid}", status, content, ts=ts,
               question=question, **kw)


class WatchTick(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state, self.old_off = mod.STATE, mod.OFF_FILE
        mod.STATE = Path(self.tmp.name) / "state.json"
        mod.OFF_FILE = Path(self.tmp.name) / "disabled"
        self.docs = [
            job_doc("task-a", "running", "fix the thing",
                    ts=NOW - timedelta(hours=2)),
            job_doc("task-b", "done", "all green",
                    ts=NOW - timedelta(hours=1)),
        ]

    def tearDown(self):
        mod.STATE, mod.OFF_FILE = self.old_state, self.old_off
        self.tmp.cleanup()

    def tick(self, docs=None, send_ok=True):
        with patch.object(mod, "mddb_job_docs",
                          return_value=self.docs if docs is None else docs), \
                patch.object(mod.board_notify, "send",
                             return_value=send_ok) as send:
            rc = mod.main()
        return rc, send

    def test_first_tick_primes_silently(self):
        rc, send = self.tick()
        self.assertEqual(rc, 0)
        send.assert_not_called()
        st = json.loads(mod.STATE.read_text())
        self.assertTrue(st["primed"])
        self.assertEqual(set(st["jobs"]), {"job/task-a", "job/task-b"})

    def test_new_state_and_new_job_notify(self):
        self.tick()  # prime
        self.docs = [
            job_doc("task-a", "done", "shipped it", ts=NOW),
            job_doc("task-b", "done", "all green",
                    ts=NOW - timedelta(hours=1)),
            job_doc("task-c", "failed", "exit=1",
                    ts=NOW - timedelta(minutes=5)),
        ]
        rc, send = self.tick()
        self.assertEqual(rc, 0)
        titles = [c.args[0] for c in send.call_args_list]
        # events report oldest-first; unchanged task-b stayed silent
        self.assertEqual(titles, ["[devin] task-c FAILED",
                                  "[devin] task-a done"])
        bodies = [c.args[1] for c in send.call_args_list]
        self.assertIn("tony-dell — exit=1", bodies[0])
        self.assertIn("tony-dell — shipped it", bodies[1])

    def test_awaiting_user_uses_question(self):
        self.tick()
        self.docs = [job_doc("task-d", "awaiting-user", "partial",
                             ts=NOW, question="which repo?")]
        _, send = self.tick()
        titles = [c.args[0] for c in send.call_args_list]
        bodies = [c.args[1] for c in send.call_args_list]
        self.assertEqual(titles, ["[devin] task-d needs input"])
        self.assertEqual(bodies, ["which repo?"])

    def test_answer_doc_notifies_answered(self):
        self.tick()
        ans = doc("answer/task-a", "answered",
                  "Answer: use the chaba repo.", kind="answer", ts=NOW)
        _, send = self.tick(docs=self.docs + [ans])
        titles = [c.args[0] for c in send.call_args_list]
        self.assertIn("[devin] task-a answered", titles)

    def test_failed_send_retains_for_retry(self):
        self.tick()
        self.docs.append(job_doc("task-e", "done", "late",
                                 ts=NOW - timedelta(minutes=1)))
        _, send = self.tick(send_ok=False)
        send.assert_called_once()
        st = json.loads(mod.STATE.read_text())
        self.assertNotIn("job/task-e", st["jobs"])
        # next tick with a healthy channel delivers it
        _, send2 = self.tick(send_ok=True)
        send2.assert_called_once()
        self.assertEqual(send2.call_args.args[0], "[devin] task-e done")

    def test_catchup_window_on_first_tick(self):
        old_catchup = mod.CATCHUP_MIN
        mod.CATCHUP_MIN = 30
        try:
            self.docs.append(job_doc("task-fresh", "done", "just now",
                                     ts=NOW - timedelta(minutes=5)))
            _, send = self.tick()
            titles = [c.args[0] for c in send.call_args_list]
            # only the in-window doc reports; history stays silent
            self.assertEqual(titles, ["[devin] task-fresh done"])
        finally:
            mod.CATCHUP_MIN = old_catchup

    def test_status_filter(self):
        old_filter = mod.STATUS_FILTER
        mod.STATUS_FILTER = {"failed"}
        try:
            self.tick()
            self.docs = [
                job_doc("task-g", "done", "quiet", ts=NOW),
                job_doc("task-h", "failed", "loud", ts=NOW),
            ]
            _, send = self.tick()
            titles = [c.args[0] for c in send.call_args_list]
            self.assertEqual(titles, ["[devin] task-h FAILED"])
        finally:
            mod.STATUS_FILTER = old_filter

    def test_kill_switch_and_env_off(self):
        mod.OFF_FILE.write_text("")
        with patch.object(mod, "mddb_job_docs") as fetch:
            self.assertEqual(mod.main(), 0)
            fetch.assert_not_called()
        mod.OFF_FILE.unlink()
        with patch.dict("os.environ",
                        {"DEVIN_DISPATCH_TG_WATCH": "off"}), \
                patch.object(mod, "mddb_job_docs") as fetch:
            self.assertEqual(mod.main(), 0)
            fetch.assert_not_called()

    def test_mddb_failure_leaves_state_untouched(self):
        with patch.object(mod, "mddb_job_docs", return_value=None):
            self.assertEqual(mod.main(), 0)
        self.assertFalse(mod.STATE.exists())


if __name__ == "__main__":
    unittest.main()
