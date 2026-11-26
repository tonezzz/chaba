"""Tests for scripts/devnest/sync-opencode-models.py — the OPS-1020
model-route registration drift guard. Synthetic profiles/opencode maps
in tempdirs only; no network, no host state writes.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/devnest/sync-opencode-models.py"

spec = importlib.util.spec_from_file_location("sync_opencode_models", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["sync_opencode_models"] = mod
spec.loader.exec_module(mod)


def run_main(argv):
    """-> (exit_code, report-dict|None)."""
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["sync-opencode-models.py"] + argv), \
            contextlib.redirect_stdout(out):
        rc = mod.main()
    text = out.getvalue().strip()
    return rc, (json.loads(text) if text else None)


class SyncModelsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.profiles = self.root / "profiles"
        self.profiles.mkdir()
        self.oc = self.root / "opencode.json"
        self.routes = self.root / "routes.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def mk_profile(self, pid, model):
        d = self.profiles / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / "profile.yml").write_text(yaml.safe_dump(
            {"id": pid, "status": "enabled", "model": model}))

    def mk_opencode(self, models=None, baseurl="http://x:4000/v1"):
        prov = {"models": models or {}}
        if baseurl is not None:
            prov["options"] = {"baseURL": baseurl}
        self.oc.write_text(json.dumps(
            {"provider": {"litellm": prov}}))

    def argv(self, *extra):
        return ["--models", "good-route,other-route",
                "--opencode", str(self.oc),
                "--profiles-root", str(self.profiles)] + list(extra)

    # ---------------------------------------------------------- routes

    def test_routes_from_config(self):
        cfg = self.root / "config.yaml"
        cfg.write_text(yaml.safe_dump({"model_list": [
            {"model_name": "a"}, {"model_name": "b"},
            {"model_name": "a"}, {"model_name": None}]}))
        self.assertEqual(mod.routes_from_config(cfg), ["a", "b"])

    # ------------------------------------------------------ providers

    def test_foreign_provider_refs_skipped(self):
        self.mk_profile("p1", {
            "tier": "cheap", "default": "litellm/good-route",
            "allowed": ["litellm/good-route", "litellm/ghost-route",
                        "opencode/big-pickle",
                        "openrouter/anthropic/claude-fable-5.1"]})
        rc, rep = run_main(self.argv())
        self.assertEqual(rc, 1)
        self.assertEqual(
            rep["breaking"],
            ["profile_route_missing: p1 allows litellm/ghost-route — "
             "no such route"])
        self.assertTrue(any("foreign_provider_refs_skipped" in n
                            for n in rep["notes"]))

    def test_bare_ref_counts_as_synced_provider(self):
        self.mk_profile("p1", {
            "tier": "cheap", "default": "ghost-route",
            "allowed": ["ghost-route"]})
        rc, rep = run_main(self.argv())
        self.assertEqual(rc, 1)
        self.assertTrue(any("ghost-route" in b
                            for b in rep["breaking"]))

    def test_empty_allowed_means_any_tier_model(self):
        # check_envelope: empty allowed list = no per-model restriction;
        # default must still be a real route but 'unallowed' can't fire
        self.mk_profile("p1", {
            "tier": "strong", "default": "good-route", "allowed": []})
        rc, rep = run_main(self.argv())
        self.assertEqual(rc, 0)
        self.assertFalse(any("unallowed" in b for b in rep["breaking"]))

    def test_disabled_profile_skipped(self):
        self.mk_profile("p1", {
            "tier": "cheap", "default": "ghost",
            "allowed": ["ghost"]})
        p = self.profiles / "p1" / "profile.yml"
        p.write_text(yaml.safe_dump(
            {"id": "p1", "status": "disabled",
             "model": {"tier": "cheap", "default": "ghost",
                       "allowed": ["ghost"]}}))
        rc, rep = run_main(self.argv())
        self.assertEqual(rc, 0)

    def test_default_unallowed_flagged(self):
        self.mk_profile("p1", {
            "tier": "cheap", "default": "other-route",
            "allowed": ["good-route"]})
        rc, rep = run_main(self.argv())
        self.assertEqual(rc, 1)
        self.assertIn(
            "profile_default_unallowed: p1 default other-route "
            "not in allowed", rep["breaking"])

    # ------------------------------------------------------ opencode map

    def test_missing_opencode_file_is_note_not_crash(self):
        rc, rep = run_main(self.argv())
        self.assertEqual(rc, 0)
        self.assertTrue(any("opencode_map_absent" in n
                            for n in rep["notes"]))

    def test_unreadable_opencode_file_is_breaking(self):
        self.oc.write_text("{not json")
        rc, rep = run_main(self.argv())
        self.assertEqual(rc, 1)
        self.assertTrue(any("opencode_map_unreadable" in b
                            for b in rep["breaking"]))

    def test_write_refuses_provider_without_baseurl(self):
        self.mk_opencode({"good-route": {"name": "x"}}, baseurl=None)
        rc, rep = run_main(self.argv("--write"))
        self.assertEqual(rc, 1)
        self.assertTrue(any("opencode_map_unwritable" in b
                            for b in rep["breaking"]))
        # file untouched — no dead stub minted
        self.assertNotIn("other-route",
                         self.oc.read_text())

    def test_write_adds_missing_keeps_stale_and_options(self):
        self.mk_opencode({"good-route": {"name": "G"},
                          "dead-route": {"name": "D"}})
        rc, rep = run_main(self.argv("--write"))
        self.assertEqual(rc, 0)
        cfg = json.loads(self.oc.read_text())
        models = cfg["provider"]["litellm"]["models"]
        self.assertIn("other-route", models)
        self.assertIn("dead-route", models)   # no --prune: kept
        self.assertEqual(
            cfg["provider"]["litellm"]["options"]["baseURL"],
            "http://x:4000/v1")

    def test_write_prune_removes_stale(self):
        self.mk_opencode({"good-route": {"name": "G"},
                          "dead-route": {"name": "D"}})
        rc, rep = run_main(self.argv("--write", "--prune"))
        self.assertEqual(rc, 0)
        models = json.loads(self.oc.read_text())[
            "provider"]["litellm"]["models"]
        self.assertNotIn("dead-route", models)
        self.assertIn("other-route", models)

    def test_check_never_writes(self):
        self.mk_opencode({"good-route": {"name": "G"}})
        before = self.oc.read_text()
        run_main(self.argv())
        self.assertEqual(self.oc.read_text(), before)

    # ------------------------------------------------------------- api

    def test_from_api_uses_key_env(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["auth"] = req.get_header("Authorization")
            return io.BytesIO(json.dumps(
                {"data": [{"id": "good-route"},
                          {"id": "other-route"}]}).encode())

        with mock.patch.object(mod.urllib.request, "urlopen",
                               fake_urlopen), \
                mock.patch.dict("os.environ",
                                {"LITELLM_KEY_CHABA": "sekret"}):
            rc, rep = run_main(
                ["--from-api", "http://x:4000/v1",
                 "--opencode", str(self.oc),
                 "--profiles-root", str(self.profiles)])
        self.assertEqual(rc, 0)
        self.assertEqual(seen["auth"], "Bearer sekret")
        self.assertEqual(rep["key_env"], "env:LITELLM_KEY_CHABA")
        # virtual keys return a per-key-filtered /v1/models — flagged
        self.assertIn("per-key", rep["route_source"])


if __name__ == "__main__":
    unittest.main()
