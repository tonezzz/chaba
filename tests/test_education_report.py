"""Deterministic verifier for scripts/education-report.py.

Fixtures only — no network. Proves the consolidated report's counts
agree with the component scripts (lessons-audit / lessons-drift /
lessons-due) on identical input, that audit mode performs zero door
mutations, and that verify/hold gating blocks notify on bad data.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "board"))

os.environ["EDU_REPORT_NOW"] = "2026-10-27T12:00:00+00:00"

spec = importlib.util.spec_from_file_location(
    "education_report", REPO / "scripts" / "education-report.py")
er = importlib.util.module_from_spec(spec)
sys.modules["education_report"] = er
spec.loader.exec_module(er)

_audit, _drift, _due = er.load_components()
_audit.TODAY = "2026-10-27"

THAI = "<p>สวัสดีครับ เนื้อหาภาษาไทย</p>" + "x" * 600
LONG_EN = "<p>" + "English body " * 80 + "</p>"


def fixture_list():
    return [
        {"slug": "lesson-ok", "topic": "healthy", "level": "intro",
         "modified": "2026-10-20T00:00:00",
         "next_review": "2026-11-01", "status": "open"},
        {"slug": "lesson-overdue", "topic": "needs review",
         "level": "working", "modified": "2026-10-01T00:00:00",
         "next_review": "2026-10-20", "status": "open"},
        {"slug": "lesson-nothai", "topic": "english only",
         "level": "intro", "modified": "2026-10-10T00:00:00",
         "next_review": "2026-11-10", "status": "open",
         "no_th": True},
        {"slug": "lesson-thin", "topic": "junk", "level": "intro",
         "modified": "2026-10-05T00:00:00",
         "next_review": "2026-11-05", "status": "open"},
        {"slug": "lesson-gone", "topic": "dead pointer",
         "level": "deep", "modified": "2026-10-15T00:00:00",
         "next_review": "2026-11-15", "status": "open"},
        {"slug": "lesson-learned", "topic": "done",
         "level": "intro", "modified": "2026-09-01T00:00:00",
         "next_review": "2026-09-10", "status": "learned"},
        {"slug": "lesson-fetchfail", "topic": "unfetchable",
         "level": "working", "modified": "2026-10-18T00:00:00",
         "next_review": "2026-11-18", "status": "open"},
    ]


def fixture_gets():
    return {
        "lesson-ok": {"content": LONG_EN + THAI,
                      "meta": {"source": "chat"}},
        "lesson-overdue": {"content": LONG_EN + THAI,
                           "meta": {"source": "voice"}},
        "lesson-nothai": {"content": LONG_EN,
                          "meta": {"source": "link", "no_th": True}},
        "lesson-thin": {"content": "<p>tiny</p>",
                        "meta": {"source": "chat"}},
        "lesson-gone": {"content": LONG_EN + THAI +
                        " see docs/definitely-missing-doc.md",
                        "meta": {"source": "chat"}},
        "lesson-learned": {"content": LONG_EN + THAI,
                           "meta": {"source": "chat"}},
        "lesson-fetchfail": {"content": "", "meta": {},
                             "error": "boom"},
    }


def data(exceptions=("lesson-nothai",)):
    return {"list": fixture_list(), "gets": fixture_gets(),
            "list_count": 7}


EXC = {"lesson-nothai": {"topic": "english only",
                       "reason": "filed --no-th"}}


def make_repo(root: Path) -> Path:
    """git repo with one committed file at a fixed date."""
    repo = root / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "real.md").write_text("x")
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-10-01T00:00:00",
               GIT_COMMITTER_DATE="2026-10-01T00:00:00")
    for cmd in (["git", "init", "-q"], ["git", "add", "."],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True, env=env)
    return repo


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = make_repo(Path(cls.tmp.name))
        cls.report = er.build(data(), cls.repo, "2026-10-27", EXC,
                              er.now_iso())
        cls.report["verify"] = er.verify(cls.report, data(), None)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def rows(self):
        return {r["slug"]: r for r in self.report["rows"]}

    def test_total_and_flag_counts_agree_with_component(self):
        r = self.report
        self.assertEqual(r["totals"]["lessons"], 7)
        # recompute flag multiset straight from audit_one on same input
        recount = {}
        for l in data()["list"]:
            g = data()["gets"][l["slug"]]
            a = _audit.audit_one(l["slug"], l["topic"], l["level"],
                                 l["next_review"], g["content"])
            fl = a["flags"] + ([f"get-failed:{g['error']}"]
                               if g.get("error") else [])
            for f in fl:
                recount[f] = recount.get(f, 0) + 1
        self.assertEqual(recount, r["policy"]["flag_counts"])

    def test_drift_rows_agree_with_component(self):
        rows = self.rows()
        self.assertIn("source-gone:docs/definitely-missing-doc.md",
                      [f for rr in self.report["drift"]["rows"]
                       for f in rr["flags"]])
        self.assertEqual(self.report["drift"]["source_gone"], 1)
        self.assertEqual(self.report["drift"]["drifted"], 0)
        # per-row flags identical to audit_content on same content
        g = data()["gets"]["lesson-gone"]
        want = _drift.audit_content(
            self.repo, "lesson-gone",
            {"topic": "dead pointer", "level": "deep"},
            "2026-10-15", g["content"])
        dr_row = [r for r in self.report["drift"]["rows"]
                  if r["slug"] == "lesson-gone"][0]
        self.assertEqual(dr_row, want)

    def test_review_buckets_agree_with_component(self):
        rv = self.report["reviews"]
        self.assertEqual((rv["due"], rv["upcoming"], rv["learned"]),
                         (1, 5, 1))
        for l in data()["list"]:
            want = _due.review_bucket(
                {"status": l["status"],
                 "next_review": l["next_review"]}, "2026-10-27")
            self.assertEqual(self.rows()[l["slug"]]["bucket"], want)

    def test_no_th_exemption(self):
        r = self.report
        self.assertEqual(r["no_th"]["exempt"], 1)
        row = self.rows()["lesson-nothai"]
        self.assertTrue(row["no_th_exempt"])
        self.assertTrue(row["checks"]["thai"])
        self.assertTrue(any(f.startswith("R5:")
                            for f in row["flags"]))

    def test_human_review_pending_explainable(self):
        pend = {h["slug"]: h for h in
                self.report["human_review_pending"]}
        self.assertIn("lesson-thin", pend)      # junk-delete candidate
        self.assertIn("lesson-gone", pend)      # source-gone pointer
        self.assertIn("lesson-overdue", pend)   # review queue
        self.assertIn("lesson-fetchfail", pend)
        for h in pend.values():
            self.assertTrue(h["reasons"])

    def test_dimensions_and_compliance(self):
        dims = self.report["policy"]["dimensions"]
        for d in er.DIMS:
            self.assertEqual(dims[d]["pass"] + dims[d]["fail"], 7)
        # fetch-failed lesson degrades to empty content: thin + no
        # Thai + empty source — real flags, not just the transport err
        self.assertEqual(dims["content"]["fail"], 2)      # thin+fetchfail
        self.assertEqual(dims["source"]["fail"], 1)       # fetchfail meta
        # overdue + learned-but-stale next_review (audit flags both —
        # it doesn't exempt the learned bucket, matching component)
        self.assertEqual(dims["next_review"]["fail"], 2)
        # nothai exempt; thin + fetchfail are real R5 fails
        self.assertEqual(dims["thai"]["fail"], 2)
        exp = sum(v["pass"] for v in dims.values()) / (7 * len(er.DIMS))
        self.assertAlmostEqual(exp,
                               self.report["policy"]["compliance"], 4)

    def test_verify_pass_and_hold_on_get_failure(self):
        v = self.report["verify"]
        self.assertEqual(v["status"], "pass")
        self.assertTrue(any(h.startswith("get_failures")
                            for h in v["holds"]))

    def test_reproducible(self):
        r2 = er.build(data(), self.repo, "2026-10-27", EXC,
                      er.now_iso())
        r2["verify"] = er.verify(r2, data(), None)
        self.assertEqual(json.dumps(self.report["rows"], sort_keys=True),
                         json.dumps(r2["rows"], sort_keys=True))
        self.assertEqual(self.report["digest"], r2["digest"])


class VerifyGating(unittest.TestCase):
    def test_torn_list_fails_verify(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            d = data()
            d["list_count"] = 99               # torn fetch
            r = er.build(d, repo, "2026-10-27", EXC, er.now_iso())
            v = er.verify(r, d, None)
            self.assertEqual(v["status"], "fail")
            self.assertTrue(any(h.startswith("verify:")
                                for h in v["holds"]))

    def test_missing_exceptions_is_a_hold(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            r = er.build(data(), repo, "2026-10-27", {}, er.now_iso())
            v = er.verify(r, data(), "missing file")
            self.assertTrue(any("exceptions" in h
                                for h in v["holds"]))


class FetchIsReadOnly(unittest.TestCase):
    """The only door ops allowed in audit mode are list and get — no
    upsert bodies, no op=delete/touch."""

    def test_fetch_all_ops_whitelist(self):
        sent = []
        real = er.api
        def fake(body, base):
            sent.append(body)
            if body.get("op") == "list":
                return {"lessons": fixture_list(), "count": 7}
            return {"content": "<p>x</p>", "meta": {}}
        er.api = fake
        try:
            er.fetch_all("http://unused")
        finally:
            er.api = real
        ops = {b.get("op") for b in sent}
        self.assertEqual(ops, {"list", "get"})
        for b in sent:
            self.assertNotIn("topic", b)      # an upsert body
            self.assertNotIn("content", b)


class EndToEnd(unittest.TestCase):
    def test_main_writes_artifacts_and_gates_post(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            fx = Path(td) / "fx.json"
            fx.write_text(json.dumps(data()))
            exc = Path(td) / "exc.yml"
            exc.write_text(
                "exceptions:\n  lesson-nothai:\n"
                "    topic: english only\n    reason: test\n")
            out = Path(td) / "out"
            argv = ["education-report.py", "--fixture", str(fx),
                    "--out-dir", str(out), "--repo", str(repo),
                    "--exceptions", str(exc), "--date", "2026-10-27",
                    "--post", "board"]
            old = sys.argv
            sys.argv = argv
            try:
                code = er.main()
            finally:
                sys.argv = old
            # get-failed fixture => hold => exit 1, notify suppressed
            self.assertEqual(code, 1)
            rep = json.loads((out / "latest.json").read_text())
            self.assertEqual(rep["notify"]["skipped"],
                             "hold/verify — see holds")
            self.assertTrue((out / "latest.md").exists())
            hist = (out / "history.jsonl").read_text().splitlines()
            self.assertEqual(len(hist), 1)
            self.assertIn("Education maintenance",
                          (out / "latest.md").read_text())


if __name__ == "__main__":
    unittest.main()
