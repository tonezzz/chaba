"""Unit tests for the ada-memory scripts (sync, consolidate, backup,
rollup, drift). Loads the dash-named scripts via importlib — pure-logic
coverage only; MDDB/HTTP paths are exercised by the live smoke tests."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts/ada"


sys.path.insert(0, str(SCRIPTS))


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
gaps = load("memory-gap-report")
staleness = load("memory-staleness-sweep")
merges = load("memory-merge-proposals")


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

    def test_draft_promoted_to_active(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            (vault / "inbox/note").mkdir(parents=True)
            (vault / "inbox/note/c.md").write_text(
                "---\nkey: note/c\nstatus: draft\nbank: note\nscope: tony\n---\ncandidate\n")
            consolidate.consolidate(vault, dry=False)
            out = (vault / "note/c.md").read_text()
            assert "status: active" in out, out
            assert "candidate" in out

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


class TestGapReport(unittest.TestCase):
    def test_parse_misses_with_query(self):
        text = (
            'bank recall \'general\': miss q="what is the wifi password" '
            "(top scores=[0.3]) — escalating to notebook\n"
            "bank recall 'note': 2 hit(s), scores=[0.7]\n"
        )
        self.assertEqual(gaps.parse_misses(text),
                         [("general", "what is the wifi password")])

    def test_parse_misses_legacy_line(self):
        # Pre-2026-09-21 builds log no q= — still counted, no query.
        text = "bank recall 'note': miss (top scores=[0.3])\n"
        self.assertEqual(gaps.parse_misses(text), [("note", None)])

    def test_norm_q_clusters_phrasing(self):
        a = gaps.norm_q("What's the Wi-Fi password?")
        b = gaps.norm_q("what is the wifi password")
        self.assertEqual(a, "what s the wi fi password")
        self.assertNotEqual(a, b)  # honest: normalization isn't semantic

    def test_unit_instance_mapping(self):
        self.assertEqual(gaps.unit_instance("ada-ha-michael.service"), "michael")
        self.assertEqual(gaps.unit_instance("ada-pi-pwa.service"), "tony")

    def test_drift_regex_still_matches_new_format(self):
        # The drift report's MISS_RE must keep matching the new q= line.
        line = 'bank recall \'x\': miss q="q" (top scores=[0.2])'
        self.assertTrue(drift.MISS_RE.search(line))


class TestStalenessSweep(unittest.TestCase):
    def test_verdict_parse(self):
        m = staleness.VERDICT_RE.match(
            "APPROVE [stale-ab12cd34] via iPhone at 2026-09-21")
        self.assertEqual((m.group(1), m.group(2)), ("APPROVE", "stale-ab12cd34"))

    def test_verdict_parse_rejects_awaiting(self):
        self.assertIsNone(
            staleness.VERDICT_RE.match("awaiting: Still true? [stale-x]"))

    def test_tag_is_stable(self):
        a = staleness.tag_for("ada-ha-bank-note-tony", "note/x")
        b = staleness.tag_for("ada-ha-bank-note-tony", "note/x")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("stale-"))


class TestMergeProposals(unittest.TestCase):
    def _doc(self, key, status="draft", source="extract", meta=None,
             body="fact body"):
        m = {"status": [status], "source": [source],
             "last_verified": ["2026-11-18"], "valid_from": ["2026-11-18"]}
        if meta:
            m.update(meta)
        return {"key": key, "contentMd": body, "meta": m}

    def test_candidate_draft_requires_extract_and_recency(self):
        d = self._doc("distill/x")
        self.assertTrue(merges.is_candidate_draft(d, 14))
        self.assertFalse(merges.is_candidate_draft(
            self._doc("v/x", source="voice"), 14))
        self.assertFalse(merges.is_candidate_draft(
            self._doc("a/x", status="active"), 14))
        self.assertFalse(merges.is_candidate_draft(
            self._doc("r/x", meta={"merge_review": ["rejected"]}), 14))
        old = self._doc("o/x", meta={"last_verified": ["2026-10-01"],
                                     "valid_from": ["2026-10-01"]})
        self.assertFalse(merges.is_candidate_draft(old, 14))

    def test_same_slot_subject_and_attribute(self):
        d = self._doc("d", meta={"subject": ["gate"], "attribute": ["loc"]})
        same = self._doc("c", status="active",
                         meta={"subject": ["gate"], "attribute": ["loc"]})
        diff_attr = self._doc("c", status="active",
                              meta={"subject": ["gate"], "attribute": ["code"]})
        self.assertTrue(merges.same_slot(d, same))
        self.assertFalse(merges.same_slot(d, diff_attr))
        # missing meta falls back to score-only matching
        nosubj = self._doc("c", status="active", meta={"subject": [""]})
        self.assertTrue(merges.same_slot(d, nosubj))

    def test_suggest_action(self):
        canon = self._doc("c", status="active",
                          meta={"subject": ["g"], "scope": ["shared"]},
                          body="The gate remote is in the drawer.")
        dup = self._doc("d", meta={"subject": ["g"], "scope": ["shared"]},
                        body="the gate remote is in the drawer.")
        self.assertEqual(merges.suggest_action(dup, canon), "reject")
        upd = self._doc("d", meta={"subject": ["g"], "scope": ["shared"]},
                        body="The gate remote moved to the cabinet.")
        self.assertEqual(merges.suggest_action(upd, canon), "update-in-place")
        rescope = self._doc("d", meta={"subject": ["g"], "scope": ["kk"]},
                            body="The gate remote moved to the cabinet.")
        self.assertEqual(merges.suggest_action(rescope, canon), "supersede")

    def test_proposal_id_stable_and_unique(self):
        a = merges.proposal_id("ada-ha-bank-general", "general/x", "distill/y")
        b = merges.proposal_id("ada-ha-bank-general", "general/x", "distill/y")
        c = merges.proposal_id("ada-ha-bank-general", "general/x", "distill/z")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith("merge-"))

    def test_draft_fact_strips_provenance_footer(self):
        d = {"contentMd": "tony decided X.\n\n---\n_distilled from 2 session(s)_\n"}
        self.assertEqual(merges.draft_fact(d), "tony decided X.")

    def test_reconcile_marks_resolutions(self):
        state = {"pairs": {"merge-1": {
            "collection": "c", "draft": "d1", "canonical": "k",
            "status": "proposed"}}}
        docs = {"c": {"d1": self._doc(
            "d1", status="superseded",
            meta={"merge_review": ["applied"]})}}
        merges.reconcile(state, docs)
        self.assertEqual(state["pairs"]["merge-1"]["status"], "applied")

    def test_reconcile_ignores_unscanned_collections(self):
        state = {"pairs": {"merge-1": {
            "collection": "other", "draft": "d1", "canonical": "k",
            "status": "proposed"}}}
        merges.reconcile(state, {})
        self.assertEqual(state["pairs"]["merge-1"]["status"], "proposed")

    def test_acceptance_rolling_window(self):
        today = "2000-01-01"  # force outside the 90d window deterministically
        state = {"pairs": {
            "a": {"status": "applied", "resolved_at": today},
            "b": {"status": "rejected", "resolved_at": today},
            "c": {"status": "proposed"},
        }}
        acc = merges.acceptance(state)
        self.assertEqual(acc["pending"], 1)
        self.assertEqual(acc["lifetime"], {"applied": 1, "rejected": 1})
        self.assertIsNone(acc["window_rate"])  # both resolved outside 90d


class TestBackupRouting(unittest.TestCase):
    def test_personal_routes_private(self):
        # privacy decision: dir prefix 'personal' -> private output dir
        for m in sync.load_bank_map():
            want = "private" if m["dir"].startswith("personal") else "repo"
            if m["bank"] == "personal":
                self.assertEqual(want, "private")
                return
        self.fail("personal bank not in registry")


class _FakeResp:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sync.requests.HTTPError(response=self)

    def json(self):
        return self._payload


class _FakeSession:
    """Plays back a list of outcomes (response or exception) per post()."""
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, url, json=None, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestMddbRetry(unittest.TestCase):
    def _mddb(self, outcomes, attempts=3):
        m = sync.Mddb("http://x", max_attempts=attempts)
        m.s = _FakeSession(outcomes)
        return m

    def test_retries_transient_then_succeeds(self):
        m = self._mddb([sync.requests.ConnectionError("reset"),
                        sync.requests.ReadTimeout("slow"),
                        _FakeResp({"ok": True})])
        with mock.patch.object(sync.time, "sleep") as sleep, \
                mock.patch.object(sync.random, "uniform", return_value=1.0):
            self.assertEqual(m._post("/add", {}), {"ok": True})
        self.assertEqual(m.s.calls, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [30, 60])

    def test_backoff_waits_are_jittered_and_bounded(self):
        m = self._mddb([sync.requests.ConnectionError("down")] * 3,
                       attempts=3)
        with mock.patch.object(sync.time, "sleep") as sleep:
            self.assertRaises(sync.requests.ConnectionError,
                              m._post, "/search", {})
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(len(waits), 2)
        # base 30/60 with ±25% jitter, capped at 90
        self.assertTrue(22.4 <= waits[0] <= 37.6, waits)
        self.assertTrue(44.9 <= waits[1] <= 75.1, waits)

    def test_exhaustion_prints_endpoint_diagnostic(self):
        m = self._mddb([sync.requests.ConnectionError("down")] * 3,
                       attempts=3)
        with mock.patch.object(sync.time, "sleep"), \
                mock.patch.object(sync.random, "uniform", return_value=1.0), \
                mock.patch("sys.stderr") as err:
            self.assertRaises(sync.requests.ConnectionError,
                              m._post, "/search", {})
        out = "".join(c.args[0] for c in err.write.call_args_list
                      if c.args)
        self.assertIn("FAILED after 3 attempts", out)
        self.assertIn("http://x", out)
        self.assertIn("not skipped", out)

    def test_exhausts_retries_and_raises(self):
        m = self._mddb([sync.requests.ConnectionError("down")] * 3,
                       attempts=3)
        with mock.patch.object(sync.time, "sleep"):
            self.assertRaises(sync.requests.ConnectionError,
                              m._post, "/search", {})
        self.assertEqual(m.s.calls, 3)

    def test_4xx_fails_fast_no_retry(self):
        m = self._mddb([_FakeResp(status=400), _FakeResp({"ok": True})])
        with mock.patch.object(sync.time, "sleep") as sleep:
            self.assertRaises(sync.requests.HTTPError, m._post, "/add", {})
        self.assertEqual(m.s.calls, 1)
        sleep.assert_not_called()

    def test_5xx_is_retried(self):
        m = self._mddb([_FakeResp(status=503), _FakeResp({"ok": True})])
        with mock.patch.object(sync.time, "sleep"):
            self.assertEqual(m._post("/add", {}), {"ok": True})
        self.assertEqual(m.s.calls, 2)

    def test_delete_404_is_benign(self):
        # /search index lags deletes — a just-deleted doc still lists and
        # /delete answers 404. Already-gone is the desired end state.
        m = self._mddb([_FakeResp(status=404)])
        m.delete("coll", "k")  # must not raise
        self.assertEqual(m.s.calls, 1)

    def test_delete_5xx_still_raises(self):
        m = self._mddb([_FakeResp(status=503)] * 3, attempts=3)
        with mock.patch.object(sync.time, "sleep"):
            self.assertRaises(sync.requests.HTTPError,
                              m.delete, "coll", "k")
        self.assertEqual(m.s.calls, 3)


class _FakeMddb:
    """Records sync() calls; serves a fixed remote doc list per collection."""
    def __init__(self, remote):
        self.remote = remote
        self.searches = []
        self.added = []
        self.deleted = []

    def list_docs(self, collection):
        self.searches.append(collection)
        return list(self.remote.get(collection, []))

    def add(self, collection, key, content, meta):
        self.added.append((collection, key))

    def delete(self, collection, key):
        self.deleted.append((collection, key))


def _vault_note(key, body="body"):
    return f"---\nkey: {key}\n---\n{body}\n"


def _remote_doc(key, writer="obsidian-vault", source="manual"):
    return {"key": key, "contentMd": "old body",
            "meta": {"written_by": [writer], "source": [source]}}


class TestSyncSharedCollection(unittest.TestCase):
    """Two bank mappings can resolve to one MDDB collection (personal/tony
    + personal-tony -> ada-ha-bank-personal-tony). The vault diff must see
    the union of both dirs — independent passes delete each other's docs."""

    def test_shared_collection_unions_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            d1 = vault / "dir-a"
            d2 = vault / "dir-b"
            d1.mkdir()
            d2.mkdir()
            (d1 / "one.md").write_text(_vault_note("k1", "new body"))
            (d2 / "two.md").write_text(_vault_note("k2", "b body"))
            mapping = [
                {"dir": "dir-a", "bank": "banka", "collection": "coll-x",
                 "scope": "sa"},
                {"dir": "dir-b", "bank": "bankb", "collection": "coll-x",
                 "scope": "sb"},
                {"dir": "dir-c", "bank": "bankc", "collection": "coll-y",
                 "scope": "sc"},
            ]
            remote = {"coll-x": [
                _remote_doc("k1"),          # vault doc, vault has newer -> update
                _remote_doc("k3"),          # vault doc, gone from vault -> delete
                _remote_doc("k9", "ada_remember", "voice"),  # voice -> keep
            ], "coll-y": []}
            fake = _FakeMddb(remote)
            old_vault = sync.VAULT
            sync.VAULT = vault
            try:
                conflicts = sync.sync(fake, mapping, dry=False,
                                      delete_remote=False, take_remote=False,
                                      take_vault=False)
            finally:
                sync.VAULT = old_vault
            self.assertEqual(conflicts, 0)
            # One search per collection, not per mapping.
            self.assertEqual(fake.searches, ["coll-x", "coll-y"])
            # k1 updated (not deleted), k3 deleted once, k2 created.
            self.assertEqual(sorted(fake.added),
                             [("coll-x", "k1"), ("coll-x", "k2")])
            self.assertEqual(fake.deleted, [("coll-x", "k3")])


if __name__ == "__main__":
    unittest.main()
