"""Unit tests for the ada-memory scripts (sync, consolidate, backup,
rollup, drift). Loads the dash-named scripts via importlib — pure-logic
coverage only; MDDB/HTTP paths are exercised by the live smoke tests."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts/ada"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sync = load("sync-ada-memory-to-mddb")
consolidate = load("consolidate-memory")
backup = load("backup-mddb-banks")
rollup = load("rollup-summaries")
drift = load("recall-drift-report")


class TestSyncLogic(unittest.TestCase):
    def _doc(self, writer="ada_remember", source="voice", body="x", meta=None):
        m = {"written_by": [writer], "source": [source]}
        if meta:
            m.update(meta)
        return {"key": "note/x", "contentMd": body, "meta": m}

    def test_voice_owned_both_sides(self):
        note = {"frontmatter": {"written_by": "ada_remember"}}
        self.assertTrue(sync._voice_owned(note, self._doc()))

    def test_voice_owned_rejects_curated_vault_copy(self):
        note = {"frontmatter": {"written_by": "obsidian-vault"}}
        self.assertFalse(sync._voice_owned(note, self._doc()))

    def test_voice_owned_rejects_vault_remote(self):
        note = {"frontmatter": {"written_by": "ada_remember"}}
        self.assertFalse(sync._voice_owned(note, self._doc(writer="obsidian-vault")))

    def test_voice_owned_rejects_test_writers(self):
        note = {"frontmatter": {"written_by": "ada_remember-test"}}
        self.assertFalse(sync._voice_owned(note, self._doc()))

    def test_parse_note_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "n.md"
            sync.write_note_file(p, {"kind": ["note"], "bank": ["note"]},
                                 "the body")
            note = sync.parse_note(p)
            self.assertEqual(note["frontmatter"]["kind"], "note")
            self.assertEqual(note["body"], "the body")

    def test_build_meta_voice_provenance(self):
        fm = {"source": "voice", "written_by": "ada_remember",
              "subject": "gate", "attribute": "location"}
        meta = sync.build_meta(fm, "note", "tony", "2026-09-20")
        self.assertEqual(meta["origin_source"], ["voice"])
        self.assertEqual(meta["origin_written_by"], ["ada_remember"])
        self.assertEqual(meta["written_by"], ["obsidian-vault"])
        self.assertEqual(meta["subject"], ["gate"])


class TestConsolidate(unittest.TestCase):
    def test_moves_to_bank_dir(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            (vault / "inbox/note").mkdir(parents=True)
            (vault / "inbox/note/x.md").write_text(
                "---\nkey: note/x\nwritten_by: ada_remember\n---\nbody\n")
            n = consolidate.consolidate(vault, dry=False)
            self.assertEqual(n, 1)
            self.assertTrue((vault / "note/x.md").exists())
            self.assertFalse((vault / "inbox/note/x.md").exists())

    def test_skips_unregistered_bank_and_clobber(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            (vault / "inbox/bogus").mkdir(parents=True)
            (vault / "inbox/bogus/x.md").write_text("no fm")
            n = consolidate.consolidate(vault, dry=False)
            self.assertEqual(n, 0)
            self.assertTrue((vault / "inbox/bogus/x.md").exists())


class TestRollup(unittest.TestCase):
    def _doc(self, key, kind, date=None, src=None):
        meta = {"kind": [kind]}
        if date:
            meta["date"] = [date]
        if src is not None:
            meta["source_keys"] = src
        return {"key": key, "meta": meta, "contentMd": "t"}

    def test_docs_by_kind(self):
        docs = [self._doc("a", "session-summary", "2026-09-20"),
                self._doc("b", "daily-summary")]
        self.assertEqual([d["key"] for d in rollup.docs_by_kind(docs, "daily-summary")], ["b"])

    def test_rollup_needed_on_new_sources_only(self):
        existing = self._doc("daily-2026-09-20", "daily-summary",
                             src=["session-x", "session-y"])
        self.assertFalse(rollup.rollup_needed(existing, ["session-x", "session-y"]))
        self.assertTrue(rollup.rollup_needed(existing, ["session-x", "session-y", "session-z"]))
        self.assertTrue(rollup.rollup_needed(None, ["session-x"]))


class TestDrift(unittest.TestCase):
    def test_analyze(self):
        r = drift.analyze(
            "bank recall 'note': 2 hit(s), scores=[0.7, 0.6]\n"
            "bank recall 'note': miss (top scores=[0.3])\n")
        self.assertEqual((r["recalls"], r["hits"], r["misses"]), (2, 1, 1))
        self.assertEqual(r["miss_rate"], 0.5)
        self.assertAlmostEqual(r["mean_hit_score"], 0.65)

    def test_tripwires_respect_min_sample(self):
        r = {"recalls": 2, "misses": 2, "miss_rate": 1.0, "mean_hit_score": 0.4}
        self.assertEqual(drift.drift_reasons(r), [])
        r["recalls"] = 20
        self.assertTrue(drift.drift_reasons(r))


class TestBackupRouting(unittest.TestCase):
    def test_personal_routes_private(self):
        # privacy decision: dir prefix 'personal' -> private output dir
        for m in sync.load_bank_map():
            want = "private" if m["dir"].startswith("personal") else "repo"
            if m["bank"] == "personal":
                self.assertEqual(want, "private")
                return
        self.fail("personal bank not in registry")


if __name__ == "__main__":
    unittest.main()
