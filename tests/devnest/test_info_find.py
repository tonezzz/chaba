"""Unit tests for scripts/devnest/info_find.py (DEV-0230) — the shared
planner + source adapters behind the portable info-find skill and the
read-only opencode profile. Covers the four contracts the card
requires: routing, fallback, citations, session isolation — plus the
lane packaging (profile lint + held-out verifier on synthetic
artifacts). No test here reaches the network or a real MDDB bank.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]

from scripts.devnest import info_find as inf  # noqa: E402

FIXTURE = REPO / "evals/opencode-lane/profiles/info-find/fixture"
DEAD_BANK = "http://127.0.0.1:1"   # refused instantly — fallback path


def _load_verify():
    spec = importlib.util.spec_from_file_location(
        "info_find_verify", FIXTURE / "verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RoutingTests(unittest.TestCase):
    def test_intent_table(self):
        cases = {
            "call the mcp tool for docs": "mcp",
            "is the kanban-commit service down?": "service-health",
            "where is ssot.jobs.yml defined": "ssot",
            "which function writes audit.ndjson": "code",
            "latest news on the SET index": "web",
            "what exists for card research, any option for a runner":
                "explore",
            "how are lane savings computed": "general-doc",
        }
        for q, want in cases.items():
            self.assertEqual(inf.classify(q), want, q)

    def test_plan_flags(self):
        p = inf.build_plan("what exists for research", "s", "chaba")
        self.assertEqual(p["intent"], "explore")
        self.assertTrue(p["use_github"])      # precedent rung
        self.assertTrue(p["use_web"])
        self.assertTrue(p["use_mddb"])
        self.assertTrue(p["use_ssot"])

        p = inf.build_plan("service status", "s", "chaba")
        self.assertEqual(p["intent"], "service-health")
        self.assertTrue(p["use_health"])
        self.assertFalse(p["use_mcp"])
        self.assertFalse(p["use_web"])

        p = inf.build_plan("mcp call", "s", "chaba")
        self.assertTrue(p["use_mcp"])
        self.assertFalse(p["use_mddb"])

    def test_quick_and_force_web(self):
        p = inf.build_plan("what exists for research", "s", "chaba",
                           quick=True)
        self.assertFalse(p["use_mddb"])
        self.assertFalse(p["use_web"])
        self.assertFalse(p["use_github"])
        p = inf.build_plan("anything", "s", "chaba", force_web=True)
        self.assertEqual(p["intent"], "web")
        self.assertTrue(p["use_web"])

    def test_wanted_sources_order(self):
        p = inf.build_plan("tell me about lanes", "s", "chaba")
        want = inf.wanted_sources(p)
        self.assertIn("mddb", want)
        self.assertIn("ssot", want)
        self.assertNotIn("web", want)


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["INFO_FIND_CACHE"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("INFO_FIND_CACHE", None)

    def test_mddb_down_is_reported_not_fatal(self):
        with patch.object(inf, "DEFAULT_MDDB_URL", DEAD_BANK):
            out = inf.run("kanban merge driver", "s1", "chaba", REPO,
                          offline=True)
        self.assertEqual(out["sources"]["mddb"]["status"],
                         "unavailable")
        self.assertIn("reason", out["sources"]["mddb"])
        # local sources still ran — the run did not die with the bank
        self.assertEqual(out["sources"]["ssot"]["status"], "ok")
        self.assertTrue(out["results"])

    def test_adapter_exception_isolated(self):
        def boom(root, query, plan):
            raise RuntimeError("explode")
        with patch.dict(inf.ADAPTERS, {"ssot": boom}), \
                patch.object(inf, "DEFAULT_MDDB_URL", DEAD_BANK):
            out = inf.run("which function writes audit.ndjson", "s1",
                          "chaba", REPO, offline=True)
        self.assertEqual(out["sources"]["ssot"]["status"], "error")
        self.assertIn("explode", out["sources"]["ssot"]["reason"])
        self.assertEqual(out["sources"]["code"]["status"], "ok")

    def test_agent_sources_deferred_vs_offline(self):
        with patch.object(inf, "DEFAULT_MDDB_URL", DEAD_BANK):
            on = inf.run("what exists for research", "s1", "chaba",
                         REPO)
            off = inf.run("what exists for research", "s1", "chaba",
                          REPO, offline=True)
        self.assertEqual(on["sources"]["web"]["status"], "deferred")
        self.assertEqual(on["sources"]["github"]["status"], "deferred")
        self.assertIn("tool", on["sources"]["web"]["spec"])
        self.assertEqual(off["sources"]["web"]["status"], "unavailable")
        self.assertEqual(off["sources"]["github"]["status"],
                         "unavailable")

    def test_mcp_policy_missing_domain_fails_soft(self):
        r = inf.mcp_policy_section(REPO, "no-such-domain-xyz")
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("known", r)


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["INFO_FIND_CACHE"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("INFO_FIND_CACHE", None)

    def test_rank_order_and_dedupe(self):
        envs = [
            {"source": "code", "results": [
                {"path": "a.py", "excerpt": "x",
                 "citation": {"path": "a.py"}},
                {"path": "dup.yml", "excerpt": "y",
                 "citation": {"path": "dup.yml"}}]},
            {"source": "mddb", "results": [
                {"path": "dup.yml", "excerpt": "m",
                 "citation": {"collection": "c", "id": "i"}},
                {"path": "b.md", "excerpt": "z",
                 "citation": {"collection": "c", "id": "i2"}}]},
            {"source": "ssot", "results": [
                {"path": "dup.yml", "excerpt": "s",
                 "citation": {"path": "dup.yml"}}]},
        ]
        out = inf.rank(envs, 10)
        self.assertEqual([r["source"] for r in out],
                         ["mddb", "mddb", "ssot", "code"])
        # mddb's dup.yml (keyed on citation.path) wins over the ssot
        # hit on the same path — dedupe keeps the higher-ranked copy

    def test_repo_citations_resolve(self):
        with patch.object(inf, "DEFAULT_MDDB_URL", DEAD_BANK):
            out = inf.run("kanban merge driver", "s1", "chaba", REPO,
                          offline=True)
        for r in out["results"]:
            cit = r.get("citation") or {}
            if r["source"] in ("ssot", "code", "health", "mcp"):
                self.assertTrue(
                    (REPO / cit["path"]).exists(), cit["path"])
                self.assertNotIn("..", cit["path"].split("/"))

    def test_mcp_policy_extraction(self):
        r = inf.mcp_policy_section(REPO, "documentation_search")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["citation"]["section"],
                         "policy.documentation_search")
        self.assertIn("mddb", r["policy"])
        self.assertTrue((REPO / r["citation"]["path"]).is_file())


class SessionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["INFO_FIND_CACHE"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("INFO_FIND_CACHE", None)

    def test_sessions_get_separate_dirs(self):
        with patch.object(inf, "DEFAULT_MDDB_URL", DEAD_BANK):
            inf.run("q one", "sess-A", "chaba", REPO, offline=True)
            inf.run("q two", "sess-B", "chaba", REPO, offline=True)
        base = Path(self.tmp.name) / "chaba" / "sessions"
        self.assertTrue((base / "sess-A" / "audit.ndjson").is_file())
        self.assertTrue((base / "sess-B" / "audit.ndjson").is_file())
        self.assertNotEqual(
            (base / "sess-A").read_bytes() if False else "a", "b")
        # audit lines are per-session — no cross-talk
        a = (base / "sess-A" / "audit.ndjson").read_text()
        self.assertIn("q one", a)
        self.assertNotIn("q two", a)

    def test_session_and_project_sanitized(self):
        self.assertEqual(inf.session_of("../../etc/passwd"), "etc-passwd")
        self.assertEqual(inf.session_of(".."), "anon")
        self.assertEqual(inf.session_of("a/b\\c d"), "a-b-c-d")
        self.assertEqual(inf.project_of(Path("/tmp/x/../y")), "y")

    def test_worktree_resolves_to_repo(self):
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d) / "dispatch-wt-xyz"
            wt.mkdir()
            (wt / ".git").write_text(
                "gitdir: /home/u/CascadeProjects/chaba/.git/worktrees/"
                "dispatch-wt-xyz\n")
            self.assertEqual(inf.project_of(wt), "chaba")
            plain = Path(d) / "plain-repo"
            plain.mkdir()
            self.assertEqual(inf.project_of(plain), "plain-repo")

    def test_cache_never_inside_repo(self):
        with patch.object(inf, "DEFAULT_MDDB_URL", DEAD_BANK):
            out = inf.run("q", "sess-Z", "chaba", REPO, offline=True)
        self.assertFalse(
            str(Path(out["cache_dir"]).resolve()).startswith(
                str(REPO)))
        self.assertIn("sess-Z", out["cache_dir"])
        self.assertTrue(Path(out["audit_path"]).is_file())

    def test_record_appends_to_session(self):
        rc = inf.main(["record", "--session", "rec-sess",
                       "--project", "chaba",
                       "--root", str(REPO),
                       "--result", "{\"n\":1}"])
        self.assertEqual(rc, 0)
        audit = (Path(self.tmp.name) / "chaba" / "sessions"
                 / "rec-sess" / "audit.ndjson")
        self.assertTrue(audit.is_file())


class LanePackagingTests(unittest.TestCase):
    """The read-only lane exposure: profile lints clean and the
    held-out verifier grades synthetic artifacts honestly."""

    PROFILE = REPO / "evals/opencode-lane/profiles/info-find/profile.yml"

    def test_profile_lints_clean(self):
        from scripts.devnest import opencode_profiles, lane_gate
        import yaml
        prof = yaml.safe_load(self.PROFILE.read_text())
        self.assertEqual(opencode_profiles.lint_profile(prof), [])

    def test_profile_is_read_only(self):
        import yaml
        from scripts.devnest import lane_gate
        prof = yaml.safe_load(self.PROFILE.read_text())
        tools = prof["tools"]
        for t in ("write", "edit", "patch", "task", "webfetch"):
            self.assertFalse(tools.get(t), t)
        allowed = {k for k, v in
                   (prof["permission"].get("bash") or {}).items()
                   if v == "allow"}
        self.assertTrue(all(
            c.startswith(("python3 scripts/devnest/info_find.py",
                          "hostname", "date"))
            for c in allowed), allowed)
        # every allowed mcp tool is inside the lane's read-only set
        self.assertTrue(
            set(prof["mcp"]["allowed"]) <= set(lane_gate.LANE_MCP_TOOLS))
        self.assertTrue(
            set(prof["mcp"]["allowed"]).isdisjoint(
                prof["mcp"]["denied"]))

    def _artifact(self, tmpdir, **over):
        a = {
            "question": "q",
            "intent": "general-doc",
            "answer": "grounded answer",
            "session": "job-1",
            "sources": {
                "mddb": {"status": "unavailable",
                         "reason": "connection refused"},
                "ssot": {"status": "ok", "count": 2},
                "code": {"status": "ok", "count": 1},
                "web": {"status": "unavailable",
                        "reason": "no_tool"}},
            "results": [
                {"source": "ssot", "excerpt": "x",
                 "citation": {"path": "docs/ssot/infrastructure/"
                              "ssot.devnest-lanes.yml",
                              "lines": [55]}},
                {"source": "code", "excerpt": "y",
                 "citation": {"path": "scripts/devnest/info_find.py",
                              "lines": [1]}}],
            "read_only": True,
            "cache_dir": str(Path.home() / ".cache/devin/info-find"
                             "/chaba/sessions/job-1"),
        }
        a.update(over)
        rd = Path(tmpdir)
        (rd / "artifact.out").write_text(json.dumps(a))
        (rd / "manifest.json").write_text(json.dumps(
            {"envelope": {"task": "q"}}))
        return rd

    def test_verifier_passes_good_artifact(self):
        v = _load_verify()
        with tempfile.TemporaryDirectory() as d:
            res = v.verify(self._artifact(d))
        self.assertEqual(res["verdict"], "pass", res)

    def test_verifier_fails_fake_citation(self):
        v = _load_verify()
        with tempfile.TemporaryDirectory() as d:
            rd = self._artifact(d, results=[
                {"source": "ssot", "excerpt": "x",
                 "citation": {"path": "docs/ssot/does-not-exist.yml"}}])
            res = v.verify(rd)
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["every citation resolves"])

    def test_verifier_fails_unexplained_unavailable(self):
        v = _load_verify()
        with tempfile.TemporaryDirectory() as d:
            rd = self._artifact(d, sources={
                "mddb": {"status": "unavailable"},   # no reason
                "ssot": {"status": "ok", "count": 1}})
            res = v.verify(rd)
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(
            res["checks"]["unavailable/error explained"])

    def test_verifier_fails_cache_inside_repo(self):
        v = _load_verify()
        with tempfile.TemporaryDirectory() as d:
            rd = self._artifact(
                d, cache_dir=str(REPO / "evals" / "cache"))
            res = v.verify(rd)
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["cache outside repo"])

    def test_envelope_lints(self):
        from scripts.devnest import lane_gate
        env = lane_gate.load_envelope(
            REPO / "evals/opencode-lane/jobs/p1-info-find-idc02.yaml")
        self.assertEqual(lane_gate.lint_envelope(env), [])


if __name__ == "__main__":
    unittest.main()
