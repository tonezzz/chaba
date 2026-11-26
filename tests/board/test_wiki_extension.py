"""Unit tests for the controlled wiki extension door on board-api
(card wiki-extension-control-plane): POST /wiki/extension ->
do_wiki_extension.

Covers the spec gates: action allowlist (list|install|enable|disable),
extension-name allowlist (no Graph/Drawio/arbitrary repos), explicit
confirm=true on mutations, honest failure on Springboard/API errors,
Special:Version before/after capture, and durable receipts.

No network: WIKI_API_CALL + WIKI_SPECIAL_VERSION seams and a tmp
WIKI_EXT_STATE dir; credentials come from a stubbed _wiki_env.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ["BOARD_API_COMMIT"] = "0"

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / "board" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeWiki:
    """Scripted MediaWiki: siteinfo extensions list + token/login/springboard
    dance. `installed` is the live set; springboard install/enable add the
    name, disable removes it (unless `sb_error` or `no_effect`)."""

    def __init__(self, installed=("Vector",), sb_error=None, no_effect=False):
        self.installed = list(installed)
        self.sb_error = sb_error
        self.no_effect = no_effect
        self.calls = []

    def __call__(self, params, post=False):
        self.calls.append((params, post))
        action = params.get("action")
        if action == "query" and params.get("meta") == "siteinfo":
            return {"query": {"extensions":
                              [{"name": n} for n in self.installed]}}
        if action == "query" and params.get("meta") == "tokens":
            if params.get("type") == "login":
                return {"query": {"tokens": {"logintoken": "lt"}}}
            return {"query": {"tokens": {"csrftoken": "csrf"}}}
        if action == "login":
            return {"login": {"result": "Success"}}
        if action == "springboard":
            if self.sb_error:
                return {"error": {"code": "permissiondenied",
                                  "info": self.sb_error}}
            if not self.no_effect:
                name = params.get("sbname")
                if params.get("sbaction") in ("install", "enable") \
                        and name not in self.installed:
                    self.installed.append(name)
                if params.get("sbaction") == "disable" \
                        and name in self.installed:
                    self.installed.remove(name)
            return {"springboard": {"result": "ok"}}
        raise AssertionError(f"unexpected api call {params}")

    def springboard_calls(self):
        return [p for p, _ in self.calls if p.get("action") == "springboard"]


class WikiExtensionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load("board-api.py")

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in
                       ("WIKI_API_CALL", "WIKI_SPECIAL_VERSION",
                        "WIKI_EXT_STATE", "_wiki_env")}
        self.tmp = Path(tempfile.mkdtemp())
        m.WIKI_EXT_STATE = self.tmp / "receipts"
        m._wiki_env = lambda: ({"WIKI_USER": "bot",
                                "WIKI_PASSWORD": "secret"},
                               "https://wiki.test/api.php")
        m.WIKI_SPECIAL_VERSION = lambda api_url: {
            "sha256": "deadbeef", "bytes": 1234}
        self.fake = FakeWiki()
        m.WIKI_API_CALL = self.fake

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.mod, k, v)

    def rejects(self, fn, frag):
        try:
            fn()
        except ValueError as e:
            self.assertIn(frag, str(e))
            return
        self.fail(f"expected ValueError {frag!r}")

    def receipts(self):
        return sorted(self.mod.WIKI_EXT_STATE.glob("*.json"))

    # --- allowlist -----------------------------------------------------

    def test_action_allowlist(self):
        self.rejects(lambda: self.mod.do_wiki_extension(
            {"action": "delete", "name": "Vector"}, "devin"),
            "list|install|enable|disable")
        self.rejects(lambda: self.mod.do_wiki_extension(
            {"action": "install", "name": "Vector",
             "confirm": True}, "devin"),
            "not approved")

    def test_name_allowlist_blocks_arbitrary(self):
        for bad in ("Graph", "Drawio", "SomeRandomExt",
                    "CategoryTree; rm -rf /"):
            self.rejects(lambda b=bad: self.mod.do_wiki_extension(
                {"action": "install", "name": b, "confirm": True},
                "devin"), "not approved")
        self.assertEqual(self.fake.springboard_calls(), [])

    # --- list ----------------------------------------------------------

    def test_list_needs_no_confirm(self):
        out = self.mod.do_wiki_extension({"action": "list"}, "devin")
        self.assertEqual(out["installed"], ["Vector"])
        self.assertIn("CategoryTree", out["approved"])
        self.assertIn("Mermaid", out["approved"])
        self.assertNotIn("Graph", out["approved"])
        self.assertNotIn("Drawio", out["approved"])
        self.assertEqual(self.fake.springboard_calls(), [])
        self.assertEqual(self.receipts(), [])

    # --- confirmation gate ----------------------------------------------

    def test_mutation_requires_confirm(self):
        for body in ({"action": "install", "name": "CategoryTree"},
                     {"action": "install", "name": "CategoryTree",
                      "confirm": "yes"},
                     {"action": "enable", "name": "Mermaid",
                      "confirm": False},
                     {"action": "disable", "name": "Lockdown"}):
            self.rejects(lambda b=body: self.mod.do_wiki_extension(
                b, "devin"), "confirm=true")
        self.assertEqual(self.fake.springboard_calls(), [])
        self.assertEqual(self.receipts(), [])

    # --- happy paths -----------------------------------------------------

    def test_install_verified_with_receipt(self):
        out = self.mod.do_wiki_extension(
            {"action": "install", "name": "CategoryTree",
             "confirm": True}, "opencode-ada")
        self.assertTrue(out["verified"])
        self.assertIn("CategoryTree", out["after"])
        self.assertTrue(out["receipt"])
        recs = self.receipts()
        self.assertEqual(len(recs), 1)
        rec = json.loads(recs[0].read_text())
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["actor"], "opencode-ada")
        self.assertEqual(rec["action"], "install")
        self.assertEqual(rec["name"], "CategoryTree")
        self.assertEqual(rec["before"]["extensions"], ["Vector"])
        self.assertIn("CategoryTree", rec["after"]["extensions"])
        self.assertEqual(rec["before"]["special_version"]["sha256"],
                         "deadbeef")
        self.assertEqual(rec["after"]["special_version"]["sha256"],
                         "deadbeef")
        # only allowlisted springboard params — no repo/branch/commit
        sb = self.fake.springboard_calls()
        self.assertEqual(len(sb), 1)
        self.assertEqual(sb[0]["sbtype"], "extension")
        self.assertEqual(sb[0]["sbname"], "CategoryTree")
        self.assertNotIn("sbrepo", sb[0])
        self.assertNotIn("sbbranch", sb[0])

    def test_disable_verified(self):
        self.fake.installed = ["Vector", "Mermaid"]
        out = self.mod.do_wiki_extension(
            {"action": "disable", "name": "Mermaid", "confirm": True},
            "devin")
        self.assertTrue(out["verified"])
        self.assertNotIn("Mermaid", out["after"])

    # --- idempotent no-op -----------------------------------------------

    def test_install_already_present_is_verified_noop(self):
        self.fake.installed = ["Vector", "CategoryTree"]
        out = self.mod.do_wiki_extension(
            {"action": "install", "name": "CategoryTree",
             "confirm": True}, "opencode-ada")
        self.assertTrue(out["verified"])
        self.assertTrue(out["no_op"])
        self.assertIn("CategoryTree", out["after"])
        # desired state already held — Springboard never invoked
        self.assertEqual(self.fake.springboard_calls(), [])
        rec = json.loads(self.receipts()[0].read_text())
        self.assertEqual(rec["status"], "ok")
        self.assertTrue(rec["verified"])
        self.assertIn("no-op", rec["note"])

    def test_enable_already_present_and_disable_already_absent(self):
        self.fake.installed = ["Vector", "Mermaid"]
        out = self.mod.do_wiki_extension(
            {"action": "enable", "name": "Mermaid", "confirm": True},
            "devin")
        self.assertTrue(out["verified"] and out["no_op"])
        out = self.mod.do_wiki_extension(
            {"action": "disable", "name": "Cargo", "confirm": True},
            "devin")
        self.assertTrue(out["verified"] and out["no_op"])
        self.assertEqual(self.fake.springboard_calls(), [])
        self.assertEqual(len(self.receipts()), 2)

    # --- honest failures -------------------------------------------------

    def test_springboard_error_is_honest_failure(self):
        self.fake.sb_error = "user lacks springboard rights"
        with self.assertRaises(self.mod.UpstreamError) as ctx:
            self.mod.do_wiki_extension(
                {"action": "install", "name": "Mermaid",
                 "confirm": True}, "devin")
        self.assertIn("springboard", str(ctx.exception))
        recs = self.receipts()
        self.assertEqual(len(recs), 1)
        rec = json.loads(recs[0].read_text())
        self.assertEqual(rec["status"], "failed")
        self.assertIn("lacks springboard", rec["error"])
        self.assertNotIn("verified", rec)

    def test_unverified_mutation_fails_without_claiming(self):
        self.fake.no_effect = True   # springboard ok but nothing changed
        with self.assertRaises(self.mod.UpstreamError) as ctx:
            self.mod.do_wiki_extension(
                {"action": "install", "name": "PageForms",
                 "confirm": True}, "devin")
        self.assertIn("not reflected", str(ctx.exception))
        rec = json.loads(self.receipts()[0].read_text())
        self.assertEqual(rec["status"], "failed")
        self.assertFalse(rec["verified"])

    def test_login_failure_is_honest(self):
        orig = self.fake.__call__

        def bad_login(params, post=False):
            if params.get("action") == "login":
                return {"login": {"result": "NeedToken"}}
            return orig(params, post)
        self.mod.WIKI_API_CALL = bad_login
        with self.assertRaises(self.mod.UpstreamError) as ctx:
            self.mod.do_wiki_extension(
                {"action": "enable", "name": "Cargo", "confirm": True},
                "devin")
        self.assertIn("login failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
