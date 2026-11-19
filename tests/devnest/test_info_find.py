import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.devnest.info_find as inf


def _plan(query, **kw):
    kw.setdefault("session", "s1")
    kw.setdefault("project", "testproj")
    kw.setdefault("quick", False)
    kw.setdefault("force_web", False)
    kw.setdefault("max_results", 5)
    kw.setdefault("mddb_collections", ["x-docs"])
    return inf.build_plan(query, **kw)


class TestRouting(unittest.TestCase):
    """Intent classification + plan flags (the router contract)."""

    def test_intent_matrix(self):
        cases = {
            "what mcp tool searches docs": "mcp",
            "is the board-api service down": "service-health",
            "systemctl status of kanban-commit": "service-health",
            "ssot.devnest-lanes routing table": "ssot",
            "where is the runner-agent function that claims":
                "code",
            "banpu stock split news": "web",
            "what exists for queued research; any tool precedent":
                "explore",
            "kanban card write path": "general-doc",
        }
        for q, want in cases.items():
            self.assertEqual(inf.classify(q), want, q)

    def test_plan_flags_general_doc(self):
        p = _plan("kanban card write path")
        self.assertTrue(p["use_mddb"] and p["use_ssot"]
                        and p["use_grep"])
        self.assertFalse(p["use_health"] or p["use_mcp"]
                         or p["use_web"])

    def test_plan_flags_web_and_quick(self):
        p = _plan("anything", force_web=True)
        self.assertEqual(p["intent"], "web")
        self.assertTrue(p["use_web"])
        p = _plan("kanban card write path", quick=True)
        self.assertFalse(p["use_mddb"] or p["use_web"])
        self.assertTrue(p["use_ssot"])

    def test_explore_defers_github_rung(self):
        p = _plan("what exists for queued research; any tool precedent")
        self.assertEqual(p["intent"], "explore")
        self.assertTrue(p["use_web"])
        self.assertTrue(p["web_query"].endswith("github"))


class TestSessionIsolation(unittest.TestCase):
    """Cache/audit isolation per project and per session."""

    def test_dirs_separate_by_session_and_project(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["INFO_FIND_CACHE_BASE"] = td
            try:
                d1 = inf._session_dir("projA", "s1")
                d2 = inf._session_dir("projA", "s2")
                d3 = inf._session_dir("projB", "s1")
                self.assertNotEqual(d1, d2)
                self.assertNotEqual(d1, d3)
                self.assertTrue(str(d1).startswith(td))
            finally:
                del os.environ["INFO_FIND_CACHE_BASE"]

    def test_audit_per_session(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["INFO_FIND_CACHE_BASE"] = td
            try:
                inf._audit("p", "s1", {"kind": "plan", "query": "a"})
                inf._audit("p", "s1", {"kind": "run", "query": "a"})
                inf._audit("p", "s2", {"kind": "plan", "query": "b"})
                a1 = (Path(td) / "p" / "sessions" / "s1"
                      / "audit.ndjson").read_text()
                a2 = (Path(td) / "p" / "sessions" / "s2"
                      / "audit.ndjson").read_text()
                self.assertEqual(len(a1.strip().splitlines()), 2)
                self.assertEqual(len(a2.strip().splitlines()), 1)
            finally:
                del os.environ["INFO_FIND_CACHE_BASE"]

    def test_task_dir_session_fallback(self):
        with patch.dict(os.environ,
                        {"TASK_DIR": "/x/y/20261119-abc"},
                        clear=False):
            os.environ.pop("DEVIN_SESSION_ID", None)
            self.assertEqual(inf._default_session(), "20261119-abc")


class TestFallbacks(unittest.TestCase):
    """Every source fails safe — recorded, never raised."""

    def test_mddb_down_marks_unavailable(self):
        p = _plan("kanban write path")
        with patch.dict(os.environ,
                        {"INFO_FIND_MDDB_URLS":
                         "http://127.0.0.1:1"}, clear=False):
            out = inf.src_mddb(p)
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["results"], [])
        self.assertIn("error", out)

    def test_run_plan_survives_dead_mddb(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "docs/ssot").mkdir(parents=True)
            (Path(root) / "docs/ssot/x.yml").write_text(
                "kanban: write path\n")
            p = _plan("kanban write path")
            p["use_web"] = p["use_mcp"] = p["use_health"] = False
            with patch.dict(os.environ,
                            {"INFO_FIND_MDDB_URLS":
                             "http://127.0.0.1:1"}, clear=False):
                out = inf.run_plan(Path(root), p, probe_health=False,
                                   web_extra=None)
        self.assertIn("mddb", out["unavailable"])
        self.assertTrue(out["results"])          # ssot/code still ran
        self.assertEqual(out["sources"]["mddb"]["status"],
                         "unavailable")

    def test_web_deferred_without_cmd(self):
        p = _plan("x", force_web=True)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INFO_FIND_WEB_CMD", None)
            out = inf.src_web(p)
        self.assertEqual(out["status"], "deferred")
        self.assertEqual(out["deferred"][0]["rung"], "web")

    def test_no_rg_stdlib_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "docs/ssot").mkdir(parents=True)
            (Path(root) / "docs/ssot/x.yml").write_text(
                "alpha beta gamma\n")
            with patch.dict(os.environ,
                            {"INFO_FIND_RG": "/nonexistent-rg"},
                            clear=False):
                hits = inf.grep_source(Path(root), "alpha beta",
                                       glob_pred=inf._pred_ssot,
                                       limit=5)
        self.assertTrue(hits)
        self.assertTrue(hits[0]["ref"].startswith("docs/ssot/x.yml:"))


class TestCitations(unittest.TestCase):
    """Ranked results always carry source+ref; dedupe + rank order."""

    def test_merge_dedupes_and_ranks(self):
        outs = [
            {"source": "code", "results": [
                {"ref": "a.py:1", "excerpt": "x", "score": 0.4}]},
            {"source": "mddb", "results": [
                {"ref": "mddb://c/k1", "excerpt": "y", "score": 0.5},
                {"ref": "mddb://c/k1", "excerpt": "y", "score": 0.5},
                {"ref": "mddb://c/k2", "excerpt": "z", "score": 0.7}]},
            {"source": "ssot", "results": [
                {"ref": "docs/ssot/a.yml:3", "excerpt": "w",
                 "score": 0.6}]},
        ]
        merged = inf.merge_results(outs, 5)
        self.assertEqual(len(merged), 4)
        self.assertEqual([r["source"] for r in merged],
                         ["mddb", "mddb", "ssot", "code"])
        self.assertEqual(merged[0]["ref"], "mddb://c/k2")
        for r in merged:
            self.assertIn("rank", r)
            self.assertIn("ref", r)
            self.assertIn("source", r)

    def test_web_extra_merges(self):
        merged = inf.merge_results(
            [{"source": "ssot", "results": [
                {"ref": "a.yml:1", "excerpt": "", "score": 0.5}]}],
            5,
            extra=[{"ref": "https://x/y", "excerpt": "w",
                    "score": 0.9}])
        self.assertEqual([r["source"] for r in merged],
                         ["web", "ssot"])

    def test_ssot_results_have_ref_and_file(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "docs/ssot").mkdir(parents=True)
            (Path(root) / "docs/ssot/a.yml").write_text(
                "kanban write path lives here\n")
            p = _plan("kanban write path")
            out = inf.src_ssot(Path(root), p)
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["results"])
        r = out["results"][0]
        self.assertRegex(r["ref"], r"^docs/ssot/a\.yml:\d+$")
        self.assertIn("excerpt", r)


class TestMcpPolicy(unittest.TestCase):
    def test_mcp_emits_deferred_policy_steps(self):
        with tempfile.TemporaryDirectory() as root:
            pdir = Path(root) / "docs/ssot/infrastructure"
            pdir.mkdir(parents=True)
            (pdir / "ssot.mcp-tools.yml").write_text(
                "title: t\npolicy:\n  documentation_search:\n"
                "    primary: mddb\n  home_assistant:\n"
                "    primary: home-assistant\nother: x\n")
            p = _plan("which mcp server for documentation")
            out = inf.src_mcp(Path(root), p)
        self.assertEqual(out["status"], "deferred")
        domains = {d["domain"]: d["primary"]
                   for d in out["deferred"][0]["domains"]}
        self.assertEqual(domains.get("documentation_search"), "mddb")
        self.assertEqual(domains.get("home_assistant"),
                         "home-assistant")


if __name__ == "__main__":
    unittest.main()
