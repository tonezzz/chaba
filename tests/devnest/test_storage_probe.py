"""Unit tests for scripts/devnest/storage_probe.py — the read-only
storage-dryrun job-pack (AUD-1033 follow-up). scan() runs against a
seeded temp tree so discovery, sizing, classification and dedup are
deterministic; verify_artifact() re-checks the emitted contract the
same way the held-out fixture/verify.py does. Read-only is proven both
structurally (no mutating calls in source) and functionally (tree
snapshot identical before/after)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "storage_probe", REPO / "scripts" / "devnest" / "storage_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PROBE = _load()


def _w(path: Path, data: bytes = b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _tree(root: Path):
    """Seeded scan tree under root/'tree': auto-kind candidates, a
    protected subtree, pruned .git, an empty dir, and a normal file."""
    t = root / "tree"
    _w(t / "pkg" / "__pycache__" / "a.pyc", b"a" * 100)
    _w(t / "pkg" / "__pycache__" / "b.pyc", b"b" * 50)
    _w(t / "pkg" / "mod.pyc", b"c" * 10)          # loose .pyc
    _w(t / "pkg" / "mod.py", b"print(1)\n")
    _w(t / ".DS_Store", b"d" * 20)
    _w(t / "node_modules" / "dep" / "__pycache__" / "x.pyc", b"n" * 5)
    _w(t / ".git" / "objects" / "aa" / "blob", b"g" * 999)
    (t / "var" / "empty").mkdir(parents=True)
    _w(t / "var" / "keep.txt", b"k" * 7)
    return t


def _manifest(root: Path, extra_proposals=()) -> Path:
    spec = {
        "scan_roots": [{"path": "tree", "desc": "seeded"}],
        "proposals": [
            {"path": "tree/pkg/__pycache__", "kind": "pycache",
             "suggested_action": "automatic_ok", "note": "seeded legit"},
            {"path": "tree/node_modules", "kind": "tmpfile",
             "suggested_action": "automatic_ok",
             "note": "TRAP: protected node_modules"},
            {"path": "tree/var/mystery.bin", "kind": "other",
             "suggested_action": "automatic_ok",
             "note": "TRAP: kind outside auto_ok_kinds"},
            *extra_proposals,
        ],
    }
    p = root / "manifest.json"
    p.write_text(json.dumps(spec))
    return p


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.tree = _tree(self.root)
        self.manifest = _manifest(self.root)

    def tearDown(self):
        self.td.cleanup()

    def _scan(self, **kw):
        return PROBE.scan(self.manifest, "storage-dryrun", self.root,
                          kw.get("max_entries", 50000))

    def test_contract_shape_and_flags(self):
        a = self._scan()
        for k in ("host", "collected_at", "roots", "candidates",
                  "refused", "deletions", "dry_run", "read_only"):
            self.assertIn(k, a, k)
        self.assertEqual(a["deletions"], [])
        self.assertIs(a["dry_run"], True)
        self.assertIs(a["read_only"], True)
        self.assertEqual(a["roots"],
                         [{"path": "tree", "exists": True,
                           "bytes": a["roots"][0]["bytes"]}])
        self.assertGreater(a["roots"][0]["bytes"], 0)

    def test_discovery_finds_auto_kinds(self):
        a = self._scan()
        by_path = {c["path"]: c for c in a["candidates"]}
        for p, kind in (("tree/pkg/__pycache__", "pycache"),
                        ("tree/pkg/mod.pyc", "pyc"),
                        ("tree/.DS_Store", "dsstore"),
                        ("tree/var/empty", "empty_dir")):
            self.assertIn(p, by_path, p)
            self.assertEqual(by_path[p]["kind"], kind)
            self.assertEqual(by_path[p]["action"], "automatic_ok", p)
        # sizes are real: pycache dir = 150 file bytes + dir overhead 0
        self.assertEqual(by_path["tree/pkg/__pycache__"]["bytes"], 150)
        self.assertEqual(by_path["tree/pkg/mod.pyc"]["bytes"], 10)

    def test_git_pruned_and_node_modules_refused(self):
        a = self._scan()
        paths = [c["path"] for c in a["candidates"]]
        self.assertFalse(any(".git" in p for p in paths))
        nm = [c for c in a["candidates"]
              if "node_modules" in c["path"]]
        self.assertTrue(nm, "node_modules/__pycache__ must be discovered")
        for c in nm:
            self.assertEqual(c["action"], "never")
            self.assertIn("protected_root", c["policy_reason"])
        refused_paths = {r["path"] for r in a["refused"]}
        self.assertTrue(any("node_modules" in p for p in refused_paths))

    def test_seeded_traps_refused(self):
        a = self._scan()
        refused = {r["path"]: r for r in a["refused"]}
        self.assertIn("tree/node_modules", refused)
        self.assertIn("protected_root", refused["tree/node_modules"]
                      ["reason"])
        self.assertIn("tree/var/mystery.bin", refused)
        self.assertIn("undeclared_kind", refused["tree/var/mystery.bin"]
                      ["reason"])
        # and they never appear as automatic_ok anywhere
        for c in a["candidates"]:
            if c["path"] in ("tree/node_modules", "tree/var/mystery.bin"):
                self.assertNotEqual(c["action"], "automatic_ok")

    def test_proposal_discovery_dedup(self):
        a = self._scan()
        hits = [c for c in a["candidates"]
                if c["path"] == "tree/pkg/__pycache__"]
        self.assertEqual(len(hits), 1, "proposal+discovery must dedupe")
        # proposal entry wins the declared path/kind; bytes still real
        self.assertEqual(hits[0]["bytes"], 150)

    def test_verify_passes_on_own_output(self):
        a = self._scan()
        art = self.root / "artifact.json"
        art.write_text(json.dumps(a))
        res = PROBE.verify_artifact(art, self.manifest,
                                    "storage-dryrun", self.root)
        self.assertEqual(res["verdict"], "pass", res["checks"])

    def test_scan_is_deterministic_modulo_volatile_fields(self):
        a1 = self._scan()
        a2 = self._scan()
        for k in ("collected_at", "host"):
            a1.pop(k); a2.pop(k)
        self.assertEqual(a1, a2)


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.tree = _tree(self.root)
        self.manifest = _manifest(self.root)
        self.art = self.root / "artifact.json"
        self.art.write_text(json.dumps(PROBE.scan(
            self.manifest, "storage-dryrun", self.root, 50000)))

    def tearDown(self):
        self.td.cleanup()

    def _verify(self, mutate=None):
        a = json.loads(self.art.read_text())
        if mutate:
            mutate(a)
        self.art.write_text(json.dumps(a))
        return PROBE.verify_artifact(self.art, self.manifest,
                                     "storage-dryrun", self.root)

    def test_good_artifact_passes(self):
        res = self._verify()
        self.assertEqual(res["verdict"], "pass")

    def test_deletions_nonempty_fails(self):
        res = self._verify(lambda a: a.update(deletions=[{"p": "x"}]))
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["deletions empty"])

    def test_dry_run_false_fails(self):
        res = self._verify(lambda a: a.update(dry_run=False))
        self.assertEqual(res["verdict"], "fail")

    def test_protected_automatic_fails(self):
        def mut(a):
            a["candidates"].append(
                {"path": "tree/node_modules/dep/__pycache__/x.pyc",
                 "kind": "pyc", "bytes": 5, "reason": "forged",
                 "action": "automatic_ok"})
        res = self._verify(mut)
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(
            res["checks"]["no automatic_ok under protected roots"])

    def test_missing_root_coverage_fails(self):
        res = self._verify(lambda a: a.update(roots=[]))
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["checks"]["all scan roots surveyed"])

    def test_trap_promoted_to_automatic_fails(self):
        def mut(a):
            # promote a seeded trap inside candidates to automatic_ok —
            # the trap check must catch it even though refused[] also
            # lists it
            for c in a["candidates"]:
                if c["path"] == "tree/node_modules":
                    c["action"] = "automatic_ok"
        res = self._verify(mut)
        self.assertEqual(res["verdict"], "fail")


class ReadOnlyProofTest(unittest.TestCase):
    def test_source_has_no_mutating_calls(self):
        src = (REPO / "scripts" / "devnest" / "storage_probe.py") \
            .read_text()
        for tok in ("os.remove", "os.unlink", "os.rmdir", "os.mkdir",
                    "os.rename", "os.replace", "os.symlink",
                    "shutil.rmtree", "shutil.move", "write_text",
                    "write_bytes", "os.chmod", "os.chown"):
            self.assertNotIn(tok, src, tok)

    def test_scan_leaves_tree_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _tree(root)
            man = _manifest(root)
            before = {str(p.relative_to(root)): (p.stat().st_size,
                                                 p.stat().st_mtime_ns)
                      for p in root.rglob("*")}
            PROBE.scan(man, "storage-dryrun", root, 50000)
            after = {str(p.relative_to(root)): (p.stat().st_size,
                                                p.stat().st_mtime_ns)
                     for p in root.rglob("*")}
            self.assertEqual(before, after)


class CliTest(unittest.TestCase):
    def test_scan_cli_emits_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _tree(root)
            man = _manifest(root)
            buf = io.StringIO()
            old = sys.stdout
            try:
                sys.stdout = buf
                rc = PROBE.main(["scan", "--manifest", str(man),
                                 "--root", str(root)])
            finally:
                sys.stdout = old
            self.assertEqual(rc, 0)
            a = json.loads(buf.getvalue())
            self.assertIs(a["dry_run"], True)
            self.assertEqual(a["deletions"], [])

    def test_verify_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _tree(root)
            man = _manifest(root)
            art = root / "a.json"
            art.write_text(json.dumps(PROBE.scan(
                man, "storage-dryrun", root, 50000)))
            buf = io.StringIO()
            old = sys.stdout
            try:
                sys.stdout = buf
                rc_ok = PROBE.main(["verify", str(art),
                                    "--manifest", str(man),
                                    "--root", str(root)])
                bad = json.loads(art.read_text())
                bad["deletions"] = [{"x": 1}]
                art.write_text(json.dumps(bad))
                rc_bad = PROBE.main(["verify", str(art),
                                     "--manifest", str(man),
                                     "--root", str(root)])
            finally:
                sys.stdout = old
            self.assertEqual(rc_ok, 0)
            self.assertEqual(rc_bad, 1)
            self.assertIn('"verdict": "pass"', buf.getvalue())


if __name__ == "__main__":
    unittest.main()
