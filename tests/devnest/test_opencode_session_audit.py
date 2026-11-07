"""Tests for scripts/devnest/opencode_session_audit.py — synthetic
sqlite store, no real opencode.db, no marker writes outside tmpdir.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/devnest/opencode_session_audit.py"

spec = importlib.util.spec_from_file_location(
    "opencode_session_audit", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["opencode_session_audit"] = mod
spec.loader.exec_module(mod)

SCHEMA = """
create table session (
  id text primary key, project_id text, workspace_id text,
  parent_id text, slug text default '', directory text default '',
  path text, title text default '', version text default '',
  share_url text, summary_additions int, summary_deletions int,
  summary_files int, summary_diffs text, metadata text,
  cost real default 0, tokens_input int default 0,
  tokens_output int default 0, tokens_reasoning int default 0,
  tokens_cache_read int default 0, tokens_cache_write int default 0,
  revert text, permission text, agent text, model text,
  time_created int, time_updated int, time_compacting int,
  time_archived int);
create table message (
  id text primary key, session_id text, time_created int,
  time_updated int, data text);
create table part (
  id text primary key, message_id text, session_id text,
  time_created int, time_updated int, data text);
"""

T0 = 1_793_000_000_000  # ms epoch


def add_session(db, sid, title="t", directory="/wt", agent="build",
                created=T0, updated=None, tokens=None):
    tokens = tokens or {}
    db.execute(
        "insert into session (id, project_id, title, directory, agent,"
        " time_created, time_updated, tokens_input, tokens_output,"
        " tokens_cache_read, tokens_cache_write, model) values"
        " (?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, "p1", title, directory, agent, created,
         updated or created + 60_000, tokens.get("input", 0),
         tokens.get("output", 0), tokens.get("cache_read", 0),
         tokens.get("cache_write", 0),
         json.dumps({"id": "m-x", "providerID": "litellm"})))


def add_msg(db, mid, sid, role, created, **kw):
    d = {"role": role, "time": {"created": created}}
    d.update(kw)
    db.execute("insert into message values (?,?,?,?,?)",
               (mid, sid, created, created, json.dumps(d)))


def add_part(db, pid, mid, sid, created, data):
    db.execute("insert into part values (?,?,?,?,?,?)",
               (pid, mid, sid, created, created, json.dumps(data)))


def user_turn(db, sid, n, text, t=T0):
    add_msg(db, f"m{n}u", sid, "user", t,
            agent="a", model={"providerID": "litellm",
                              "modelID": "m-x"})
    add_part(db, f"p{n}ut", f"m{n}u", sid, t + 1,
             {"type": "text", "text": text})


def tool_part(db, sid, n, tool, inp, status="completed", error="",
              t=T0, mid=None):
    mid = mid or f"m{n}a"
    state = {"status": status, "input": inp,
             "time": {"start": t, "end": t + 100}}
    if error:
        state["error"] = error
    add_msg(db, mid, sid, "assistant", t,
            modelID="m-x", providerID="litellm",
            tokens={"input": 10, "output": 5, "reasoning": 0,
                    "cache": {"read": 0, "write": 0}},
            time={"created": t, "completed": t + 50})
    add_part(db, f"p{n}t", mid, sid, t + 2,
             {"type": "tool", "tool": tool, "callID": f"c{n}",
              "state": state})


def text_part(db, sid, n, text, t=T0, mid=None):
    mid = mid or f"m{n}a"
    add_part(db, f"p{n}x", mid, sid, t + 3,
             {"type": "text", "text": text})


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db_path = self.dir / "opencode.db"
        self.db = sqlite3.connect(self.db_path)
        self.db.executescript(SCHEMA)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def ro_db(self):
        self.db.commit()
        return mod.open_db(self.db_path)

    def audit(self, sid="s1"):
        self.db.commit()
        db = mod.open_db(self.db_path)
        sess = mod.list_sessions(db, 0, [sid])[0]
        return mod.audit_session(db, sess, {})

    def test_clean_readonly_session(self):
        add_session(self.db, "s1", directory="/wt/clean",
                    agent="ops-readonly")
        user_turn(self.db, "s1", 1, "report on host health")
        tool_part(self.db, "s1", 1, "bash", {"command": "hostname"})
        tool_part(self.db, "s1", 2, "read", {"filePath": "/etc/os-release"})
        text_part(self.db, "s1", 3, "All read-only, report attached.")
        rec = self.audit()
        self.assertEqual(rec["prompt_count"], 1)
        self.assertEqual(rec["tools"]["total"], 2)
        self.assertEqual(rec["tools"]["denied"], 0)
        self.assertEqual(rec["mutations"]["count"], 0)
        self.assertEqual(rec["safety_flags"], [])
        self.assertEqual(rec["model"], "m-x")
        self.assertEqual(rec["provider"], "litellm")

    def test_denied_signature_detected(self):
        add_session(self.db, "s1", agent="ops-readonly")
        user_turn(self.db, "s1", 1, "do stuff")
        tool_part(self.db, "s1", 1, "bash", {"command": "ls /etc"},
                  status="error",
                  error="The user has specified a rule which prevents "
                        "you from using this specific tool call.")
        rec = self.audit()
        self.assertEqual(rec["tools"]["denied"], 1)
        self.assertEqual(rec["tools"]["errors"], 0)
        kinds = {f["kind"] for f in rec["findings"]}
        self.assertIn("denied_tool", kinds)

    def test_plain_error_not_denial(self):
        add_session(self.db, "s1")
        user_turn(self.db, "s1", 1, "x")
        tool_part(self.db, "s1", 1, "grep", {"pattern": "a"},
                  status="error", error="ripgrep exploded")
        rec = self.audit()
        self.assertEqual(rec["tools"]["errors"], 1)
        self.assertEqual(rec["tools"]["denied"], 0)

    def test_bash_mutation_smuggling(self):
        add_session(self.db, "s1", agent="ops-readonly")
        user_turn(self.db, "s1", 1, "x")
        tool_part(self.db, "s1", 1, "bash",
                  {"command": "git push origin master"})
        tool_part(self.db, "s1", 2, "bash",
                  {"command": "rm -rf /tmp/junk"})
        tool_part(self.db, "s1", 3, "bash",
                  {"command": "echo hi > /tmp/out.txt"})
        tool_part(self.db, "s1", 4, "bash",
                  {"command": "python3 -c \"open('/tmp/p','w')"
                              ".write('x')\""})
        tool_part(self.db, "s1", 5, "bash",
                  {"command": "git commit -m x"})
        rec = self.audit()
        m = rec["mutations"]
        self.assertEqual(len(m["pushes"]), 1)
        self.assertEqual(len(m["deletes"]), 1)
        self.assertEqual(len(m["commits"]), 1)
        self.assertGreaterEqual(len(m["writes"]), 2)  # > + python -c
        self.assertTrue(any("mutation outside profile scope" in f
                            for f in rec["safety_flags"]))

    def test_write_tool_and_durability(self):
        target = self.dir / "landed.json"
        target.write_text("{}")  # a write that actually landed
        add_session(self.db, "s1")
        user_turn(self.db, "s1", 1, "x")
        tool_part(self.db, "s1", 1, "write",
                  {"filePath": str(target), "content": "{}"})
        tool_part(self.db, "s1", 2, "write",
                  {"filePath": "/nonexistent-dir-xyzzy/missing.json",
                   "content": "{}"})
        tool_part(self.db, "s1", 3, "write",
                  {"filePath": "/tmp/ephem.json", "content": "{}"})
        # tmpdir lives under /tmp — neutralise the ephemeral rule so the
        # landed file asserts "exists" not "ephemeral"
        with mock.patch.object(mod, "EPHEMERAL_ROOTS", ("/nope/",)):
            rec = self.audit()
        by = {a["path"]: a["verdict"] for a in rec["artifacts"]}
        self.assertEqual(by[str(target)], "exists")
        self.assertEqual(by["/nonexistent-dir-xyzzy/missing.json"],
                         "missing")
        self.assertEqual(by["/tmp/ephem.json"], "missing")
        kinds = [f["kind"] for f in rec["findings"]]
        self.assertIn("artifact_not_durable", kinds)

    def test_ephemeral_verdict(self):
        add_session(self.db, "s1")
        user_turn(self.db, "s1", 1, "x")
        tool_part(self.db, "s1", 1, "write",
                  {"filePath": "/tmp/ephem.json", "content": "{}"})
        rec = self.audit()
        self.assertEqual(rec["artifacts"][0]["verdict"], "ephemeral")

    def test_durable_existing_file(self):
        target = self.dir / "real.md"
        target.write_text("hi")
        add_session(self.db, "s1")
        user_turn(self.db, "s1", 1, "x")
        tool_part(self.db, "s1", 1, "write",
                  {"filePath": str(target), "content": "hi"})
        with mock.patch.object(mod, "EPHEMERAL_ROOTS", ("/nope/",)):
            rec = self.audit()
        self.assertEqual(rec["artifacts"][0]["verdict"], "exists")

    def test_claims_without_evidence(self):
        add_session(self.db, "s1")
        user_turn(self.db, "s1", 1, "x")
        add_msg(self.db, "m9a", "s1", "assistant", T0 + 9)
        text_part(self.db, "s1", 9,
                  "Done — wrote /home/tony/nowhere/report.md and "
                  "filed card nonexistent-card-xyz.", mid="m9a")
        rec = self.audit()
        claims = rec["claims_without_evidence"]
        self.assertTrue(any("report.md" in c["claim"] for c in claims))
        self.assertTrue(any("nonexistent-card-xyz" in c["claim"]
                            for c in claims))

    def test_retries_detected(self):
        add_session(self.db, "s1")
        user_turn(self.db, "s1", 1, "x")
        tool_part(self.db, "s1", 1, "bash", {"command": "hostname"},
                  status="error", error="denied-ish", t=T0)
        tool_part(self.db, "s1", 2, "bash", {"command": "hostname"},
                  status="completed", t=T0 + 1000)
        rec = self.audit()
        self.assertEqual(rec["retries"]["count"], 1)

    def test_token_mismatch_flag(self):
        add_session(self.db, "s1",
                    tokens={"input": 100000, "output": 5})
        user_turn(self.db, "s1", 1, "x")
        tool_part(self.db, "s1", 1, "read", {"filePath": "/etc/hosts"})
        rec = self.audit()
        self.assertTrue(rec["tokens"]["mismatch"])

    def test_sequence_anomaly(self):
        add_session(self.db, "s1",
                    directory="/tmp/opencode-s1-canary.XYZ/mcp",
                    created=T0)
        user_turn(self.db, "s1", 1, "x")
        rec = mod.audit_session(
            self.ro_db(), mod.list_sessions(self.ro_db(), 0, ["s1"])[0],
            {"S1": mod.ms_to_iso(T0 + 999_000)})
        self.assertTrue(any("sequence_anomaly" in f
                            for f in rec["safety_flags"]))
        rec2 = mod.audit_session(
            self.ro_db(), mod.list_sessions(self.ro_db(), 0, ["s1"])[0],
            {"S1": mod.ms_to_iso(T0 - 999_000)})
        self.assertFalse(any("sequence_anomaly" in f
                             for f in rec2["safety_flags"]))

    def test_ungated_profile_run(self):
        add_session(self.db, "s1", agent="ssot-research")
        user_turn(self.db, "s1", 1, "x")
        self.db.commit()
        db = self.ro_db()
        sess = mod.list_sessions(db, 0, ["s1"])[0]
        rec = mod.audit_session(db, sess, {})
        runs = self.dir / "runs"
        runs.mkdir()
        empty_state = self.dir / "no-state"
        res = mod.reconcile_lane_runs(db, runs, {"s1": rec},
                                      state_dir=empty_state)
        self.assertEqual(len(res["ungated_profile_sessions"]), 1)
        kinds = {f["kind"] for f in rec["findings"]}
        self.assertIn("ungated_profile_run", kinds)

    def test_lane_run_evidence_link(self):
        add_session(self.db, "s1", agent="ops-readonly")
        user_turn(self.db, "s1", 1, "x")
        self.db.commit()
        db = self.ro_db()
        sess = mod.list_sessions(db, 0, ["s1"])[0]
        rec = mod.audit_session(db, sess, {})
        runs = self.dir / "runs" / "job1-2026"
        runs.mkdir(parents=True)
        (runs / "events.jsonl").write_text(json.dumps(
            {"type": "step_start", "sessionID": "s1"}) + "\n")
        (runs / "run.json").write_text(json.dumps(
            {"job": "job1", "verdict": "pass",
             "artifact_landed": True}))
        res = mod.reconcile_lane_runs(db, runs.parent, {"s1": rec},
                                      state_dir=self.dir / "no-state")
        self.assertEqual(res["ungated_profile_sessions"], [])
        self.assertEqual(res["runs"][0]["session_id"], "s1")
        self.assertEqual(rec["governance"], "lane_gated")

    def test_dispatch_rails_not_ungated(self):
        add_session(
            self.db, "s1", agent="ops-readonly",
            directory="/home/tony/CascadeProjects/dispatch-wt-foo-12345")
        user_turn(self.db, "s1", 1,
                  "task\n---\nRails: you are processing kanban card "
                  "'x' on runner 'y'.")
        self.db.commit()
        db = self.ro_db()
        sess = mod.list_sessions(db, 0, ["s1"])[0]
        rec = mod.audit_session(db, sess, {})
        res = mod.reconcile_lane_runs(db, self.dir / "runs",
                                      {"s1": rec},
                                      state_dir=self.dir / "no-state")
        self.assertEqual(res["ungated_profile_sessions"], [])
        self.assertEqual(rec["governance"], "dispatch_rails")

    def test_ledger_epoch_not_ungated(self):
        add_session(
            self.db, "s1", agent="ops-readonly",
            directory="/home/tony/CascadeProjects/"
                      "dispatch-wt-pilot-1793330282")
        user_turn(self.db, "s1", 1, "x")
        state = self.dir / "state"
        state.mkdir()
        (state / "metrics.jsonl").write_text(json.dumps(
            {"job_id": "pilot-1793330282"}) + "\n")
        self.db.commit()
        db = self.ro_db()
        sess = mod.list_sessions(db, 0, ["s1"])[0]
        rec = mod.audit_session(db, sess, {})
        res = mod.reconcile_lane_runs(db, self.dir / "runs",
                                      {"s1": rec}, state_dir=state)
        self.assertEqual(res["ungated_profile_sessions"], [])
        self.assertEqual(rec["governance"], "ledger_recorded")

    def test_contamination(self):
        add_session(self.db, "s1",
                    directory="/home/tony/CascadeProjects/"
                              "dispatch-wt-aaa")
        user_turn(
            self.db, "s1", 1,
            "work on kanban card 'alpha-beta-gamma' please. also see "
            "kanban card 'delta-eps-zeta'")
        tool_part(self.db, "s1", 1, "read",
                  {"filePath": "/home/tony/CascadeProjects/"
                               "dispatch-wt-bbb/x.py"})
        rec = self.audit()
        self.assertTrue(rec["contamination"]["flagged"])
        self.assertIn("dispatch-wt-bbb",
                      " ".join(rec["contamination"]["worktree_roots"]))

    def test_window_listing(self):
        add_session(self.db, "old", created=T0 - 99_000_000,
                    updated=T0 - 98_000_000)
        add_session(self.db, "new", created=T0)
        self.db.commit()
        db = self.ro_db()
        got = {s["id"] for s in mod.list_sessions(db, T0 - 1000, [])}
        self.assertEqual(got, {"new"})
        got_all = {s["id"] for s in mod.list_sessions(db, 0, [])}
        self.assertEqual(got_all, {"old", "new"})

    def test_marker_semantics(self):
        m = self.dir / "marker"
        since, note = mod.resolve_marker(m)
        self.assertIn("24h", note)
        self.assertGreater(since, 0)
        m.write_text("2026-10-27T00:00:00Z\n")
        since, note = mod.resolve_marker(m)
        self.assertEqual(since, mod.iso_to_ms("2026-10-27T00:00:00Z"))
        mod.write_marker(m)
        self.assertTrue(m.read_text().strip().endswith("Z"))

    def test_shadow_reconcile(self):
        sh = self.dir / "shadow"
        rp = self.dir / "reports"
        sh.mkdir()
        rp.mkdir()
        (sh / "2026-10-27-shadow-benchmark.json").write_text(
            json.dumps({"at": "a", "runs": [
                {"arm": "opencode", "fixture": "f1",
                 "verdict": "pass"},
                {"arm": "opencode", "fixture": "f2",
                 "verdict": "fail"}]}))
        (rp / "2026-10-27-promotion-review.json").write_text(
            json.dumps({"at": "b", "decision": "promote",
                        "promote_to": "S1",
                        "aggregate": {"jobs": 5, "verified": 3}}))
        res = mod.reconcile_shadow(sh, rp)
        self.assertEqual(res["benchmarks"][0]["opencode_pass"], 1)
        self.assertEqual(len(res["discrepancies"]), 1)
        self.assertIn("non-deterministic",
                      res["discrepancies"][0]["verdict"])

    def test_card_id_stable(self):
        cid = mod.card_id_for("artifact_not_durable",
                              "ses_abc123XYZ")
        self.assertTrue(cid.startswith("audit-oc-artifact-not-durable-"))
        self.assertLessEqual(len(cid), 80)


if __name__ == "__main__":
    unittest.main()
