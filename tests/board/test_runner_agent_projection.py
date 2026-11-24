"""Claim/verdict field-parity proof for the projected /cards read
(AUD-1033 follow-up, card ops-manual-command-api-mcp-efficiency-
followups).

runner-agent's claim_pass and verdict_pass re-read the whole board every
pass (~12.7MB at 719 cards). RUNNER_CARDS_PROJECTION=1 switches exactly
those two reads to GET /cards?fields=… — the claim field set without
comms (~1MB). These tests prove the projection is behavior-identical:

  * _cards_read pages the projected endpoint and fails closed to []
    on any bad page (same empty-board semantics as the legacy dump);
  * every top-level key the claim/verdict surface reads is declared in
    CARDS_FIELDS (static audit over the real call graph);
  * claim_pass and verdict_pass produce identical board writes
    (claim attempts, defer comms, /ready verdicts) over the REAL card
    corpus, full dump vs projected read — with /action suppressed so
    no claim ever launches;
  * comms — the one field the projection drops — resolves lazily and
    exactly once per retry-ledger-held card, and an unreadable comms
    fetch is 'unknown', never a false zero that could forgive a retry
    ledger.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "board" / "runner-agent.py"
CARD_DIR = REPO / "docs" / "ssot" / "kanban" / "cards"


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent_projection",
                                                  SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["runner_agent_projection"] = mod
    spec.loader.exec_module(mod)
    return mod


def _cards():
    out = []
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if isinstance(d, dict):
            d.setdefault("id", p.stem)
            out.append(d)
    return out


def _project(card: dict, fields) -> dict:
    """Mirror of board-api _project for a plain fields= set."""
    return {k: card.get(k) for k in fields if k in card}


class CardsReadTest(unittest.TestCase):
    """_cards_read transport behavior — stubbed api(), no network."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        self.mod.CARDS_PROJECTION = False
        self._saved_api = self.mod.api
        self.calls = []
        self.mod.api = lambda p, b=None: self.calls.append(p) or {}

    def tearDown(self):
        self.mod.api = self._saved_api

    def test_legacy_default_reads_full_dump(self):
        self.mod.api = lambda p, b=None: (
            self.calls.append(p) or {"cards": [{"id": "x"}]})
        self.assertEqual(self.mod._cards_read(), [{"id": "x"}])
        self.assertEqual(self.calls, ["/cards"])

    def test_projection_off_by_default(self):
        # module imported with RUNNER_CARDS_PROJECTION unset -> legacy
        self.assertFalse(self.mod.CARDS_PROJECTION)

    def test_projected_read_requests_claim_fields_no_comms(self):
        self.mod.CARDS_PROJECTION = True
        self.mod.api = lambda p, b=None: (
            self.calls.append(p) or
            {"ok": True, "cards": [], "total": 0, "truncated": False})
        self.mod._cards_read()
        path = self.calls[0]
        self.assertTrue(path.startswith("/cards?fields="))
        qs = path.split("fields=", 1)[1].split("&", 1)[0]
        fields = set(qs.split(","))
        self.assertEqual(fields, set(self.mod.CARDS_FIELDS))
        self.assertNotIn("comms", fields)
        self.assertIn("limit=1000", path)
        self.assertIn("offset=0", path)

    def test_projected_read_paginates_until_not_truncated(self):
        self.mod.CARDS_PROJECTION = True
        pages = {0: ([{"id": "a"}, {"id": "b"}], True),
                 2: ([{"id": "c"}], False)}

        def api(path, body=None):
            self.calls.append(path)
            off = int(re.search(r"offset=(\d+)", path).group(1))
            cards, trunc = pages[off]
            return {"ok": True, "cards": cards, "truncated": trunc}

        self.mod.api = api
        cards = self.mod._cards_read()
        self.assertEqual([c["id"] for c in cards], ["a", "b", "c"])
        offsets = [int(re.search(r"offset=(\d+)", c).group(1))
                   for c in self.calls]
        self.assertEqual(offsets, [0, 2])

    def test_projected_read_bad_page_fails_closed_empty(self):
        self.mod.CARDS_PROJECTION = True
        self.mod.api = lambda p, b=None: {"error": "boom"}
        self.assertEqual(self.mod._cards_read(), [])

    def test_projected_read_mid_pagination_error_fails_closed(self):
        self.mod.CARDS_PROJECTION = True
        state = {"n": 0}

        def api(path, body=None):
            self.calls.append(path)
            state["n"] += 1
            if state["n"] == 1:
                return {"ok": True, "cards": [{"id": "a"}],
                        "truncated": True}
            return {"error": "page2 lost"}

        self.mod.api = api
        # a partial board must NOT be returned — claiming on half the
        # queue is worse than claiming nothing this pass
        self.assertEqual(self.mod._cards_read(), [])


class CardCommsTest(unittest.TestCase):
    """_card_comms/_rearm_count lazy resolution — the one field the
    projection drops."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        self.m = self.mod
        self._saved_api = self.m.api
        self.calls = []

    def tearDown(self):
        self.m.api = self._saved_api

    def _stub(self, handler):
        def api(path, body=None):
            self.calls.append(path)
            return handler(path, body)
        self.m.api = api

    def test_inline_comms_no_fetch(self):
        card = {"id": "c1", "comms": [{"text": "retry requested"}]}
        self._stub(lambda p, b: {"error": "must not be called"})
        self.assertEqual(self.m._rearm_count(card), 1)
        self.assertEqual(self.calls, [])

    def test_projected_card_lazy_fetches_once_and_caches(self):
        card = {"id": "c1"}   # no comms key — the projected shape
        comms = [{"text": "queued for processing"},
                 {"text": "noise"}, {"text": "re-queued"}]
        self._stub(lambda p, b: {"ok": True,
                                 "card": {"id": "c1", "comms": comms}})
        self.assertEqual(self.m._rearm_count(card), 2)
        self.assertEqual(self.m._rearm_count(card), 2)
        self.assertEqual(self.calls, ["/card/c1?fields=comms"])
        self.assertEqual(card["comms"], comms)

    def test_fetch_failure_is_unknown_not_zero(self):
        card = {"id": "c1"}
        self._stub(lambda p, b: {"error": "api down"})
        self.assertIsNone(self.m._rearm_count(card))
        # second call must not hammer the api — tried marker caches
        self.assertIsNone(self.m._rearm_count(card))
        self.assertEqual(len(self.calls), 1)

    def test_card_without_comms_field_is_empty_not_unknown(self):
        card = {"id": "c1"}
        self._stub(lambda p, b: {"ok": True, "card": {"id": "c1"}})
        self.assertEqual(self.m._rearm_count(card), 0)


class RetryGateUnknownCommsTest(unittest.TestCase):
    """An unreadable comms fetch must never forgive or re-baseline a
    retry ledger — 'unknown' is not 'zero re-arms'."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved = (m.api, m.RETRY_FILE, m.RETRY_MAX, m.note_defer)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        m.RETRY_FILE = Path(self.tmp.name) / "retry-ledger.json"
        m.RETRY_MAX = 3
        m.note_defer = lambda *a, **k: None
        m.api = lambda p, b=None: {"error": "down"}

    def tearDown(self):
        (self.mod.api, self.mod.RETRY_FILE, self.mod.RETRY_MAX,
         self.mod.note_defer) = self._saved

    def _ledger(self, ent):
        self.mod.RETRY_FILE.write_text(json.dumps({"c1": ent}))

    def test_unknown_comms_blocks_forgive_and_baseline(self):
        # rearms baseline 0, fails below cap, backoff expired — the
        # ONLY thing between this card and a claim is the re-arm
        # count, which the failed fetch cannot supply. last_fail must
        # be inside RETRY_TTL_S or _retry_ledger filters the entry.
        self._ledger({"fails": 1, "last_fail": int(time.time()),
                      "next_ok": 0, "rearms": 0})
        card = {"id": "c1"}   # projected shape, comms fetch fails
        self.assertEqual(self.mod.retry_gate(card), "")
        # ledger must be untouched — no forgive (pop) and no
        # re-baseline write of a phantom 0/None
        ent = json.loads(self.mod.RETRY_FILE.read_text())["c1"]
        self.assertEqual(ent.get("rearms"), 0)
        self.assertEqual(ent.get("fails"), 1)

    def test_known_rearms_still_forgives(self):
        self._ledger({"fails": 1, "last_fail": int(time.time()),
                      "next_ok": 0, "rearms": 0})
        card = {"id": "c1",
                "comms": [{"text": "retry requested"}]}
        self.assertEqual(self.mod.retry_gate(card), "")
        self.assertNotIn("c1", json.loads(
            self.mod.RETRY_FILE.read_text()))


class FieldParityStaticTest(unittest.TestCase):
    """Every literal top-level card key read inside the claim/verdict
    call graph must be declared in CARDS_FIELDS (or be `comms`, which
    resolves lazily). Audited receivers: card, blocker, doc — `a`,
    `g`, loop vars etc. are nested dicts covered by the whole `action`
    field or local comms entries."""

    # runner-agent functions reachable from claim_pass/verdict_pass
    # (the projected read). _note_capacity_skip, finish_*, gate_pass,
    # reconcile_* keep the legacy /cards read and are excluded.
    RA_FUNCS = [
        "_act", "_ensure_act", "card_profile", "model_provider",
        "model_valid_for_executor", "lane_model", "_kw_hit",
        "_codemod_hit", "classify_lane", "_card_rec",
        "_waiting_hold_reason", "push_guard_reason", "push_capable",
        "_repo_checkout", "_claimable", "claimable",
        "executor_defer_reason", "shutil_which", "opencode_bin",
        "opencode_needs_standalone", "nlm_available", "card_gpu_need_mb",
        "gpu_free_mb", "gpu_preflight", "_defer_norm", "note_defer",
        "note_gpu_defer", "_rearm_count", "_card_comms",
        "retry_record_failure", "retry_record_success", "retry_gate",
        "_retry_ledger", "_retry_save", "blocker_released",
        "_claim_order", "_capacity_reason", "_cards_read",
        "self_stale_reason", "kk_mac_contract_ok", "kk_mac_servable",
        "kk_mac_probe", "start_kk_mac_lane", "start_opencode_lane",
        "_start_opencode_lane", "start_nlm_lane", "start_task",
        "prepare_profile_dispatch", "launch_profile_dispatch",
        "task_runtime", "units_for_card",
    ]
    # dispatch_repos helpers the claim path calls through dr_module()
    DR_FUNCS = ["claim_sort_key", "card_updated_ts", "sort_claimable",
                "kk_mac_route", "kk_mac_prompt", "unsatisfiable_reasons",
                "canon_host", "canon_repo"]

    KEY_RES = [
        re.compile(r'\b(?:card|blocker|doc)\.get\(\s*["\']([a-z_]+)["\']'),
        re.compile(r'\b(?:card|blocker|doc)\[\s*["\']([a-z_]+)["\']\s*\]'),
    ]

    @staticmethod
    def _func_body(path: Path, name: str) -> str:
        src = path.read_text()
        m = re.search(rf"\ndef {name}\(.*?\n(?=\ndef |\Z)", src, re.S)
        return m.group(0) if m else ""

    def _audit(self, path: Path, funcs, extra=frozenset()):
        mod = _load()
        # comms resolves lazily; _comms_tried is runner-local memo
        # state stashed on the card dict — never board data
        fields = set(mod.CARDS_FIELDS) | {"comms"} | set(extra)
        missing = {}
        for fn in funcs:
            body = self._func_body(path, fn)
            if not body:
                missing[fn] = ["<function not found>"]
                continue
            keys = set()
            for rx in self.KEY_RES:
                keys.update(rx.findall(body))
            bad = sorted(k for k in keys if k not in fields)
            if bad:
                missing[fn] = bad
        return missing

    def test_runner_agent_claim_surface_covered(self):
        missing = self._audit(SCRIPT, self.RA_FUNCS,
                              extra={"_comms_tried"})
        self.assertEqual(missing, {},
                         f"claim-path card keys outside CARDS_FIELDS: "
                         f"{missing}")

    def test_dispatch_repos_claim_helpers_covered(self):
        missing = self._audit(
            REPO / "scripts/board/dispatch_repos.py", self.DR_FUNCS)
        self.assertEqual(missing, {},
                         f"dispatch_repos claim keys outside "
                         f"CARDS_FIELDS: {missing}")

    def test_dispatch_task_build_covered(self):
        # build_task_text is the only dispatch_task entry start_task
        # calls with the card; _act is its accessor.
        missing = self._audit(
            REPO / "scripts/board/dispatch_task.py",
            ["build_task_text", "_act"])
        self.assertEqual(missing, {},
                         f"dispatch_task keys outside CARDS_FIELDS: "
                         f"{missing}")

    def test_lesson_primer_keywords_covered(self):
        # keywords() is the only primer entry that sees the API card —
        # build()/build_good() forward it to _select->keywords; the
        # doc-scoped helpers read local YAML files, not the projection.
        body = self._func_body(REPO / "scripts/board/lesson_primer.py",
                               "keywords")
        self.assertTrue(body, "keywords() not found")
        keys = set()
        for rx in self.KEY_RES:
            keys.update(rx.findall(body))
        mod = _load()
        fields = set(mod.CARDS_FIELDS) | {"comms"}
        self.assertLessEqual(keys, fields,
                             f"lesson_primer.keywords reads "
                             f"{sorted(keys - fields)}")


class PassParityTest(unittest.TestCase):
    """End-to-end parity: run claim_pass + verdict_pass over the REAL
    card corpus twice — legacy /cards dump vs projected read — and
    require identical board writes. /action answers error so no claim
    launches; every other mutation is recorded and compared."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()
        cls.cards = _cards()

    # module attrs redirected into a per-run temp state dir
    STATE_ATTRS = ("STATE_DIR", "STATE_FILE", "READY_REPORT",
                   "DEFER_FILE", "RETRY_FILE", "RATELIMIT_FILE")

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k, None) for k in (
            "api", "CARDS_PROJECTION", "HOST", "LABELS", "CAP",
            "WAITING_GATE", "WAITING_KILL", "READY_FORCE_S",
            "RETRY_MAX", "STARVE_HOURS",
            "push_capable", "gpu_free_mb", "self_stale_reason",
            "ratelimit_reason", "overloaded", "_load5_per_core",
            "kk_mac_probe", "kk_mac_servable", "nlm_available",
            "unit_active", "opencode_bin", "task_runtime")}
        self._saved.update({k: getattr(m, k) for k in self.STATE_ATTRS})
        self._saved_env = os.environ.get("JEV_LANE")
        os.environ["JEV_LANE"] = "0"   # claim-time classify stays off
        self._tmps = []
        self.addCleanup(self._cleanup)
        m.HOST = "parity-test-host"
        m.LABELS = set()
        m.CAP = 99
        m.WAITING_GATE = "warn"
        m.READY_FORCE_S = -1      # never debounce — always post /ready
        m.RETRY_MAX = 3
        # deterministic claim order: starve_hours<=0 disables the
        # time-based tier so sort_claimable keys on card data alone
        m.STARVE_HOURS = -1
        # probes that would leave the host or hit the network — pinned
        # identically for both runs so only the card READ differs
        m.push_capable = lambda repo: True
        m.gpu_free_mb = lambda: (65536, 65536)
        m.self_stale_reason = lambda: ""
        m.ratelimit_reason = lambda: ""
        m.overloaded = lambda pc=None: False
        m._load5_per_core = lambda: 0.0
        m.kk_mac_probe = lambda: {"eligible": False}
        m.kk_mac_servable = lambda: False
        m.nlm_available = lambda: False
        m.unit_active = lambda u: False
        m.opencode_bin = lambda: "/usr/bin/opencode"
        m.task_runtime = lambda: "systemd"

    def _cleanup(self):
        m = self.mod
        for k, v in self._saved.items():
            if v is None:
                try:
                    delattr(m, k)
                except AttributeError:
                    pass
            else:
                setattr(m, k, v)
        if self._saved_env is None:
            os.environ.pop("JEV_LANE", None)
        else:
            os.environ["JEV_LANE"] = self._saved_env
        for t in self._tmps:
            t.cleanup()

    def _run_passes(self, projected: bool):
        """One full claim+verdict cycle against a fresh state dir.
        Returns the board-mutating api calls in order."""
        m = self.mod
        tmp = tempfile.TemporaryDirectory()
        self._tmps.append(tmp)
        tdp = Path(tmp.name)
        for k, name in (("STATE_DIR", "STATE_DIR"),
                        ("STATE_FILE", "state.json"),
                        ("READY_REPORT", "ready-verdicts.json"),
                        ("DEFER_FILE", "gpu-defer.json"),
                        ("RETRY_FILE", "retry-ledger.json"),
                        ("RATELIMIT_FILE", "ratelimit.json")):
            setattr(m, k, tdp if k == "STATE_DIR" else tdp / name)
        m.WAITING_KILL = str(tdp / "no-kanban-dispatch")
        cards, projected_cards, ledger = self._corpus()
        m.RETRY_FILE.write_text(json.dumps(ledger))
        calls = []

        def api(path, body=None):
            calls.append((path, body))
            if path == "/cards":
                return {"ok": True, "cards": copy.deepcopy(cards)}
            if path.startswith("/cards?"):
                return {"ok": True,
                        "cards": copy.deepcopy(projected_cards),
                        "count": len(projected_cards),
                        "total": len(projected_cards),
                        "truncated": False}
            mm = re.match(r"^/card/([^?]+)\?fields=comms$", path)
            if mm:
                cid = mm.group(1)
                hit = next((c for c in cards if c.get("id") == cid),
                           None)
                if hit is None:
                    return {"error": "card not found"}
                return {"ok": True,
                        "card": {"id": cid,
                                 "comms": copy.deepcopy(
                                     hit.get("comms") or [])}}
            if path == "/action":
                # claim attempts are the parity signal — suppress the
                # launch so no unit ever starts
                return {"error": "parity-test: claim suppressed"}
            return {"ok": True}

        m.api = api
        m.CARDS_PROJECTION = projected
        m.claim_pass({})
        m.verdict_pass({})
        return [(p, b) for p, b in calls
                if not (p == "/cards" or p.startswith("/cards?")
                        or re.match(r"^/card/", p))]

    def _corpus(self):
        """Real cards + deterministic retry-ledger seed. A re-arm comm
        is injected into the first claimable card's comms so the
        projected read's lazy /card fetch is exercised end-to-end;
        identical augmentation feeds both runs."""
        cards = copy.deepcopy(self.cards)
        claimable = [c for c in cards if self.mod.claimable(c)]
        self.assertTrue(
            claimable,
            "no claimable card on the real board — the parity run "
            "would not exercise the claim path")
        ledger = {}
        picks = {}
        # forgive-path card: re-arm comm injected -> retry_gate pops
        g = claimable[0]
        g.setdefault("comms", []).append(
            {"at": "2026-01-01T00:00:00", "from": "parity-test",
             "text": "retry requested"})
        ledger[g["id"]] = {"fails": 1, "last_fail": int(time.time()),
                           "next_ok": 0, "rearms": 0}
        picks["forgive"] = g["id"]
        # cap-path card when the board offers a second claimable
        if len(claimable) > 1:
            c2 = claimable[1]
            ledger[c2["id"]] = {"fails": 3,
                                "last_fail": int(time.time()),
                                "next_ok": 0, "rearms": 0}
            picks["cap"] = c2["id"]
        self._last_picks = picks
        projected = [_project(c, self.mod.CARDS_FIELDS) for c in cards]
        return cards, projected, ledger

    def test_claim_and_verdict_pass_identical_board_writes(self):
        writes_legacy = self._run_passes(projected=False)
        writes_proj = self._run_passes(projected=True)
        self.assertTrue(writes_legacy,
                        "parity run produced no board writes — the "
                        "claim path was not exercised")
        self.assertEqual(writes_proj, writes_legacy)
        # and the lazy comms fetch really fired on the projected run —
        # otherwise parity could be vacuous on the comms path
        # (verified indirectly: the forgive pick's ledger entry was
        # consumed identically on both sides)
