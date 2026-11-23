"""Codemod-lane gate tests (dispatch-lane-classifier-codemod-keyword-false-positive, OPS-0028).

Bare-substring codemod keywords routed judgment work to the cheap
deterministic lane — 'lock' matched block/clock/unlock (ADA-1285 hit
codemod on "tools block" in its spec), and 'config'/'cap'/'flag'/
'script'/'raise '/'change the' matched any spec discussing them.

The gate is now: word-boundary matching; codemod keywords are
TITLE-scoped; the spec body counts only through LANE_KW['codemod_body']
multi-word phrases; codemod needs a title hit OR >=2 distinct hits.
The vendored runner-agent copy is asserted identical to
dispatch_repos.LANE_KW so the two classifiers cannot drift again.
"""

from __future__ import annotations

import importlib.util
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[2]
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / "board" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_card(card_id):
    # regression fixtures name real cards — they must keep loading after
    # the board archives them (live first, then archive)
    for base in (CARDS, CARDS / "archive"):
        p = base / f"{card_id}.yml"
        if p.exists():
            return yaml.safe_load(p.read_text())
    raise FileNotFoundError(card_id)


def _unpinned(card):
    """Card copy with classifier/explicit lane pins stripped — forces
    the keyword path even when the card carries a prior stamp."""
    c = dict(card)
    a = dict(card.get("action") or {})
    a.pop("lane", None)
    a.pop("lane_source", None)
    c["action"] = a
    return c


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos")
        cls.ra = _load("runner-agent")

    def setUp(self):
        # jevos is not part of these tests — force the devin-safe
        # fallback so both classifiers resolve identically offline.
        self._p = patch.object(urllib.request, "urlopen",
                               side_effect=OSError("jevos stubbed"))
        self._p.start()
        self.addCleanup(self._p.stop)

    def lane(self, card):
        return self.dr.classify_lane(card)


class LockstepTest(_Base):
    def test_lane_kw_dicts_identical(self):
        """The vendored runner-agent copy must be a verbatim copy of
        dispatch_repos.LANE_KW — drift between the two classifiers is
        how remote hosts silently misroute (free_lane had already
        drifted 9 keywords before this test existed)."""
        self.assertEqual(self.dr.LANE_KW, self.ra.LANE_KW)
        self.assertEqual(self.dr.LANE_COMPARE, self.ra.LANE_COMPARE)

    def test_codemod_body_entries_are_multiword(self):
        """Body-eligible codemod entries must be multi-word phrases —
        single words in the spec body are context, not transforms."""
        for kw in self.dr.LANE_KW["codemod_body"]:
            self.assertGreaterEqual(len(kw.split()), 2, kw)

    def test_broad_single_words_dropped(self):
        """The words named in the false-positive card must not return
        as bare codemod keywords."""
        for kw in ("config", "lock", "script"):
            self.assertNotIn(kw, self.dr.LANE_KW["codemod"])

    def test_kw_hit_word_boundary(self):
        for mod in (self.dr, self.ra):
            self.assertFalse(mod._kw_hit("lock", "the block by the clock"))
            self.assertFalse(mod._kw_hit("lock", "unlock the door"))
            self.assertFalse(mod._kw_hit("cap", "capacity planning"))
            self.assertFalse(mod._kw_hit("flag", "flagship feature"))
            self.assertTrue(mod._kw_hit("lock", "a file lock held"))
            self.assertTrue(mod._kw_hit("cap", "cap the retries"))
            # multi-word phrases span any whitespace run
            self.assertTrue(mod._kw_hit("change the", "change   the"))
            self.assertTrue(mod._kw_hit("copies task tests",
                                        "copies\ntask tests"))


class CodemodGateTest(_Base):
    def test_ada1285_not_codemod(self):
        """The reported FP: a generator-script + verb-design card hit
        codemod via 'lock' inside 'tools block'. Re-classifying the
        real card (its kw-stamped lane is re-evaluated) must not
        return codemod."""
        card = _load_card("ada-tools-command-reference")
        lane, source, conf = self.dr.classify_lane(card, with_detail=True)
        self.assertNotEqual(lane, "codemod",
                            f"{card['id']} still routes codemod "
                            f"(source={source})")
        self.assertNotEqual(self.ra.classify_lane(card), "codemod")

    def test_spend_false_manual_cards_not_codemod(self):
        """The two cards named in dispatch-lane-classifier-spend-false-
        manual are judgment/diagnosis work — re-classified (pins
        stripped) they must not land on codemod either."""
        for cid in ("idc03-gemini-ollama-proxy-paid-fallback-2fa021",
                    "ada-real-card-sweep-scenario-20261108"):
            card = _unpinned(_load_card(cid))
            for mod in (self.dr, self.ra):
                self.assertNotEqual(mod.classify_lane(card), "codemod",
                                    f"{cid} routes codemod on {mod}")

    def test_block_clock_lockfile_body_not_codemod(self):
        """A spec whose only codemod-ish tokens are block/clock/
        'lock file' must not classify codemod."""
        card = {"id": "c1", "title": "digest timer housekeeping note",
                "spec": "the block sits around the clock and a lock file "
                        "guards the job; nothing else mentions transforms",
                "action": {}}
        for mod in (self.dr, self.ra):
            self.assertNotEqual(mod.classify_lane(card), "codemod")

    def test_codemod_singles_in_body_not_codemod(self):
        """Body mentions of title-scoped singles (cap/flag/inject) are
        context — they do not even count toward the >=2 gate."""
        card = {"id": "c1", "title": "weekly digest reliability review",
                "spec": "discussion: a cap on retries, a flag for the "
                        "new path, where to inject the probe",
                "action": {}}
        for mod in (self.dr, self.ra):
            self.assertNotEqual(mod.classify_lane(card), "codemod")

    def test_single_body_phrase_alone_not_codemod(self):
        """One strong phrase in the body is still just one hit."""
        card = {"id": "c1", "title": "transcript retention review",
                "spec": "options include whether we should delete old "
                        "transcripts; needs a retention decision first",
                "action": {}}
        for mod in (self.dr, self.ra):
            self.assertNotEqual(mod.classify_lane(card), "codemod")

    def test_two_body_phrases_is_codemod(self):
        """Two distinct codemod_body phrases with a quiet title =
        known-transform work — the >=2 gate lets it through."""
        card = {"id": "c1", "title": "monthly checkpoint maintenance",
                "spec": "delete old checkpoint files and convert the "
                        "cleanup to a nest job",
                "action": {}}
        for mod in (self.dr, self.ra):
            self.assertEqual(mod.classify_lane(card), "codemod")

    def test_bump_title_still_codemod(self):
        card = {"id": "c1",
                "title": "bump pinned dependency version in mddb-embed",
                "spec": "the pinned version is stale", "action": {}}
        for mod in (self.dr, self.ra):
            self.assertEqual(mod.classify_lane(card), "codemod")
        lane, source, conf = self.dr.classify_lane(card, with_detail=True)
        self.assertEqual(source, "kw:bump")

    def test_retire_flag_title_still_codemod(self):
        card = {"id": "c1",
                "title": "retire flag ada-legacy-mode across configs",
                "spec": "remove the flag and its branches",
                "action": {}}
        for mod in (self.dr, self.ra):
            self.assertEqual(mod.classify_lane(card), "codemod")

    def test_remove_title_still_codemod(self):
        """Existing behavior preserved: a transform verb in the title
        is decisive on its own."""
        card = {"id": "c1", "title": "remove unused config",
                "action": {}}
        for mod in (self.dr, self.ra):
            self.assertEqual(mod.classify_lane(card), "codemod")

    def test_explicit_codemod_pin_untouched(self):
        """An author-declared action.lane=codemod is the author's own
        routing — the gate never overrides it."""
        card = {"id": "c1", "title": "anything at all",
                "action": {"lane": "codemod"}}
        for mod in (self.dr, self.ra):
            self.assertEqual(mod.classify_lane(card), "codemod")

    def test_classifier_parity_on_regression_cards(self):
        """dr and the vendored runner-agent classify every regression
        fixture identically (with jevos stubbed, dr's fallback is the
        same 'devin' the vendored copy returns)."""
        fixtures = [_load_card("ada-tools-command-reference"),
                    _unpinned(_load_card(
                        "idc03-gemini-ollama-proxy-paid-fallback-2fa021")),
                    _unpinned(_load_card(
                        "ada-real-card-sweep-scenario-20261108")),
                    {"id": "x", "title": "digest timer housekeeping",
                     "spec": "the block by the clock uses a lock file",
                     "action": {}},
                    {"id": "x",
                     "title": "bump pinned dependency version in mddb",
                     "spec": "", "action": {}},
                    {"id": "x", "title": "hardware rotation",
                     "spec": "", "action": {}}]
        for card in fixtures:
            self.assertEqual(self.dr.classify_lane(card),
                             self.ra.classify_lane(card),
                             f"parity miss on {card.get('id')}: "
                             f"{card.get('title')}")


if __name__ == "__main__":
    unittest.main()
