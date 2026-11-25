#!/usr/bin/env python3
"""Offline unit tests for lane-retention.py + prune-old-docs.py policy.

Pure-logic coverage: filename/session-id parsing, slug derivation (incl.
non-latin subjects), transcript lane-claim + upload gating, the extract
scope/privacy gate, and the per-lane ops TTL policy table. MDDB/ssh/NLM
paths are stubbed — the live smoke is the weekly dry-run on idc03.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "ada"
sys.path.insert(0, str(SCRIPTS))


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lr = load("lane-retention")
prune = load("prune-old-docs")


def doc(key, **meta):
    return {"key": key, "lang": "en", "contentMd": "body",
            "meta": {k: [str(v)] for k, v in meta.items()}}


class Args:
    lane = "kk"
    include_shared = False
    dry_run = False
    min_age_days = 2
    max_per_run = 500
    max_groups = 25
    merge_singletons = False


def mkargs(**kw):
    a = Args()
    for k, v in kw.items():
        setattr(a, k, v)
    return a


class TestFilenameParse(unittest.TestCase):
    def test_standard_name(self):
        m = lr.FN_RE.match("2026-10-07-3117139945.md")
        self.assertEqual(m.groups(), ("2026-10-07", "3117139945"))

    def test_rejects_non_session_files(self):
        for bad in ("notes.md", "2026-10-07.md", "x-3117139945.md",
                    "2026-10-07-XYZ123.md"):
            self.assertIsNone(lr.FN_RE.match(bad), bad)


class TestSlugs(unittest.TestCase):
    def test_latin(self):
        self.assertEqual(lr.base_slug("Language Preference!"),
                         "language-preference")

    def test_thai_fallback_is_unique(self):
        a = lr.slugify("คุณน้ำพุ")
        b = lr.slugify("พี่แดน")
        self.assertTrue(a.startswith("s-") and b.startswith("s-"))
        self.assertNotEqual(a, b)   # no bank/misc collapse

    def test_extract_subject_normalization(self):
        self.assertEqual(lr.base_slug("language-preference"),
                         lr.base_slug("language preference"))


class TestTranscriptClaim(unittest.TestCase):
    """Only lane-attributed transcripts upload; unknowns remain local."""

    def _run(self, lane="kk", upload_ok=True, sids=None,
             state=None):
        cfg = lr.LANES[lane]
        args = mkargs(lane=lane)
        state = state if state is not None else {"transcripts": {}}
        calls = []
        with tempfile.TemporaryDirectory():
            with patch.object(lr, "lane_sids",
                              return_value=set(sids or ["aa11bb22"])), \
                 patch.object(lr, "journal_sids", return_value=set()), \
                 patch.object(lr, "list_transcripts",
                              return_value=[("2026-10-01-aa11bb22.md",
                                             "2026-10-01"),
                                            ("2026-10-02-cc33dd44.md",
                                             "2026-10-02")]), \
                 patch.object(lr, "notebook_titles", return_value=set()), \
                 patch.object(lr, "fetch_transcript",
                              return_value="t"), \
                 patch.object(lr, "nlm_add_text",
                              side_effect=lambda *a: (
                                  "src-1" if upload_ok else None)), \
                 patch.object(lr, "save_state"):
                lr.nlm_add_text_real = lr.nlm_add_text
                up, skip = lr.archive_transcripts(lane, cfg, args, state)
                calls.append(state)
        return up, skip, state

    def test_lane_claims_its_sid(self):
        up, skip, st = self._run()
        self.assertEqual(up, 1)
        self.assertIn("idc03/2026-10-01-aa11bb22.md", st["transcripts"])

    def test_unmapped_stays_local(self):
        up, skipped, st = self._run()
        self.assertEqual(up, 1)   # only the claimed file
        self.assertEqual(skipped, 1)
        self.assertNotIn("idc03/2026-10-02-cc33dd44.md",
                         st["transcripts"])

    def test_failed_upload_not_recorded(self):
        up, _, st = self._run(upload_ok=False)
        self.assertEqual(up, 0)
        self.assertEqual(st["transcripts"], {})

    def test_state_dedup_skips_prior(self):
        state = {"transcripts": {"idc03/2026-10-01-aa11bb22.md":
                                 {"title": "t"}}}
        up, skip, _ = self._run(state=state)
        self.assertEqual((up, skip), (0, 2))  # dedup + unclaimed


class TestLaneInventory(unittest.TestCase):
    def test_dev_archive_scope_is_bounded(self):
        # ada-pi-pwa included per Tony's 2026-11-18 decision (lane=dev);
        # anything beyond these confirmed dev units is still out of scope.
        cfg = lr.LANES["dev"]
        self.assertEqual(cfg["hosts"], ["idc03"])
        self.assertEqual(cfg["units"], {"idc03": ["ada-dev", "ada-kk-dev",
                                                  "ada-pi-pwa"]})

    def test_michael_journal_uses_current_service_name(self):
        self.assertEqual(lr.LANES["michael"]["units"]["idc03"],
                         ["ada-ai-kraut"])


class TestOpsPolicy(unittest.TestCase):
    def test_every_lane_collection_in_policy(self):
        for lane, cfg in lr.LANES.items():
            for coll in cfg["collections"]:
                self.assertIn(coll, prune.POLICY, f"{lane} missing {coll}")

    def test_all_instances_have_events_and_snapshots(self):
        for inst in prune.ADA_INSTANCES:
            self.assertEqual(prune.POLICY[f"ada-ha-events-{inst}"],
                             ("period_end", 30))
            self.assertEqual(prune.POLICY[f"ada-ha-snapshots-{inst}"],
                             ("refreshed_at", 30))

    def test_ada_collections_swept_on_both_bases(self):
        self.assertEqual(prune.collection_bases("ada-ha-events-kk"),
                         [prune.ADA_OPS_MDB, prune.MDDB])
        self.assertEqual(prune.collection_bases("host-logs"),
                         [prune.OPS_MDB])

    def test_actions_not_pruned(self):
        for inst in prune.ADA_INSTANCES:
            self.assertNotIn(f"ada-ha-actions-{inst}", prune.POLICY)


class TestSweepOps(unittest.TestCase):
    """sweep_ops returns bare line strings — the summary phase regexes
    'deleted N/' off them. A (line, ok) tuple result must be unwrapped
    here, not downstream (ADA-1370: tuples exit-coded all four lanes
    on 2026-11-25)."""

    def _run(self, results):
        it = iter(results)
        with patch.object(lr.prune, "collection_bases",
                          return_value=["http://ops/v1"]), \
             patch.object(lr.prune, "sweep",
                          side_effect=lambda *a: next(it)):
            return lr.sweep_ops(lr.LANES["kk"], dry=True)

    def test_string_results_pass_through(self):
        line = "ada-ha-events-kk: deleted 3/10 (>30d on period_end)"
        self.assertEqual(self._run([line, line]), [line, line])

    def test_tuple_results_become_bare_lines(self):
        lines = self._run([("ada-ha-events-kk: deleted 1/2", True),
                           ("ada-ha-snapshots-kk: would delete 0/4",
                            False)])
        self.assertEqual(lines, ["ada-ha-events-kk: deleted 1/2",
                                 "ada-ha-snapshots-kk: would delete 0/4"])
        self.assertTrue(all(isinstance(l, str) for l in lines))

    def test_non_string_results_dropped(self):
        self.assertEqual(
            self._run([None, ("x: deleted 0/1", True)]),
            ["x: deleted 0/1"])


class TestMainOpsOnly(unittest.TestCase):
    """End-to-end --ops-only run: tuple-returning prune.sweep must not
    crash the summary/card_comment phase (the reported failure)."""

    def test_main_completes_with_tuple_sweep_results(self):
        posted = []
        with tempfile.TemporaryDirectory() as td, \
             patch.object(sys, "argv",
                          ["lane-retention.py", "--lane", "kk",
                           "--ops-only"]), \
             patch.object(lr, "STATE", Path(td) / "state.json"), \
             patch.object(lr.prune, "collection_bases",
                          return_value=["http://ops/v1"]), \
             patch.object(lr.prune, "sweep",
                          return_value=("x: deleted 2/5", True)), \
             patch.object(lr, "card_comment",
                          side_effect=lambda t: posted.append(t)), \
             patch.object(lr, "ops_event"), \
             patch.object(lr.chaba_event, "send"), \
             patch.object(lr, "save_state"):
            rc = lr.main()
        self.assertEqual(rc, 0)
        # 2 collections x 1 base x 'deleted 2/5' = 4 docs swept
        self.assertEqual(len(posted), 1)
        self.assertIn("4 ops docs swept", posted[0])


class _FakeMddb:
    """list_docs stub + writes captured."""

    instances = []

    def __init__(self, docs):
        self.docs = docs
        self.added = []
        self.patched = []
        self.timeout = 20
        self.base = "mddb://test"
        self.s = types.SimpleNamespace(patch=self._patch)
        _FakeMddb.instances.append(self)

    def _patch(self, url, json=None, timeout=None):
        self.patched.append(json)
        return types.SimpleNamespace(status_code=200)

    def list_docs(self, collection):
        return self.docs

    def add(self, collection, key, content, meta):
        self.added.append((collection, key, content, meta))


def extract(key, status="draft", scope="kk", subject="S", bank="kk-bank",
            kind="fact"):
    return doc(key, status=status, scope=scope, subject=subject,
               bank=bank, kind=kind, source="extract",
               written_by="conversation_memory")


class TestExtractMerge(unittest.TestCase):
    def _run(self, docs, scopes, generate_ret="merged body", lane="kk"):
        _FakeMddb.instances.clear()
        fake = _FakeMddb(docs)
        args = mkargs(lane=lane)
        with patch.object(lr.ada_sync, "Mddb", return_value=fake), \
             patch.object(lr.ada_sync, "load_bank_map", return_value=[
                 {"bank": "kk-bank", "collection": "c1",
                  "writable": True, "dir": "x", "scope": "kk"}]), \
             patch.object(lr.gemini_rest, "generate",
                          return_value=generate_ret):
            return lr.merge_extracts(lr.LANES[lane], scopes, args), fake

    def test_group_merges_into_new_draft_canonical(self):
        docs = [extract("extract-1", subject="Music"),
                extract("extract-2", subject="music"),
                extract("extract-3", status="superseded")]  # skipped
        (merged, sup), fake = self._run(docs, {"kk"})
        self.assertEqual((merged, sup), (1, 2))
        coll, key, content, meta = fake.added[0]
        self.assertEqual(key, "kk-bank/music")
        self.assertEqual(meta["status"], ["draft"])        # review gate
        self.assertEqual(sorted(meta["source_keys"]),
                         ["extract-1", "extract-2"])
        sup_keys = sorted(p["key"] for p in fake.patched)
        self.assertEqual(sup_keys, ["extract-1", "extract-2"])
        for p in fake.patched:
            self.assertEqual(p["meta"]["status"], ["superseded"])
            self.assertEqual(p["meta"]["superseded_by"], ["kk-bank/music"])

    def test_all_active_group_promotes_active(self):
        docs = [extract("extract-1", status="active"),
                extract("extract-2", status="active")]
        (merged, sup), fake = self._run(docs, {"kk"})
        self.assertEqual(fake.added[0][3]["status"], ["active"])

    def test_scope_gate_blocks_lane_into_shared(self):
        docs = [extract("extract-1", scope="kk", subject="Tony"),
                extract("extract-2", scope="kk", subject="Tony"),
                doc("people/tony", status="active", scope="shared",
                    subject="tony")]
        (merged, sup), fake = self._run(docs, {"kk"})
        self.assertEqual((merged, sup), (0, 0))
        self.assertEqual(fake.added, [])

    def test_shared_members_can_update_shared_canon(self):
        docs = [extract("extract-1", scope="shared", subject="Tony"),
                extract("extract-2", scope="shared", subject="Tony"),
                doc("people/tony", status="active", scope="shared",
                    subject="tony")]
        (merged, sup), fake = self._run(docs, {"shared"})
        self.assertEqual((merged, sup), (1, 2))
        # existing canonical -> content updated, status preserved
        coll, key, content, meta = fake.added[0]
        self.assertEqual(key, "people/tony")
        self.assertEqual(meta["status"], ["active"])
        self.assertIn("extract-1", meta["source_keys"])

    def test_superseded_canonical_chases_target(self):
        docs = [extract("extract-1", subject="X"),
                extract("extract-2", subject="X"),
                doc("kk-bank/x-old", status="superseded", subject="x",
                    superseded_by="kk-bank/x-new"),
                doc("kk-bank/x-new", status="active", scope="kk")]
        (merged, sup), fake = self._run(docs, {"kk"})
        self.assertEqual(fake.added[0][1], "kk-bank/x-new")

    def test_dead_canonical_falls_back_to_create(self):
        docs = [extract("extract-1", subject="X"),
                extract("extract-2", subject="X"),
                doc("kk-bank/x-old", status="superseded", subject="x")]
        (merged, sup), fake = self._run(docs, {"kk"})
        self.assertEqual(fake.added[0][1], "kk-bank/x")

    def test_singleton_waits_for_siblings(self):
        docs = [extract("extract-1", subject="alone")]
        (merged, sup), fake = self._run(docs, {"kk"})
        self.assertEqual((merged, sup), (0, 0))

    def test_singleton_folds_into_existing_canonical(self):
        docs = [extract("extract-1", subject="X", scope="kk"),
                doc("kk-bank/x", status="active", scope="kk",
                    subject="x")]
        (merged, sup), fake = self._run(docs, {"kk"})
        self.assertEqual((merged, sup), (1, 1))

    def test_empty_llm_keeps_sources(self):
        docs = [extract("extract-1"), extract("extract-2")]
        (merged, sup), fake = self._run(docs, {"kk"},
                                        generate_ret="")
        self.assertEqual((merged, sup), (0, 0))
        self.assertEqual(fake.patched, [])


if __name__ == "__main__":
    unittest.main()
