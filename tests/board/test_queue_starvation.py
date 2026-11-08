"""Unit tests for queue-type-starvation-guard: a card whose action.type
is not 'dispatch' can never be claimed by kanban-dispatch, so queueing
one must be loud, not silent (2026-10-13 zombie-sweep: 6 cards queued
for days, zero claims, no skip log line).

Covers all three legs of the fix:
  - board-api queue_starve_warn + do_action/do_create warn the queuer
    (and never auto-flip the type)
  - kanban-dispatch prints a skip reason instead of a bare `continue`
  - board-invariants Q1 flags a non-dispatch card starved >24h

Imports the dash-named modules via importlib; no dispatch, no git, no
network (BOARD_API_COMMIT=0 keeps save() out of the repo's git index).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["BOARD_API_COMMIT"] = "0"  # tmp card dirs aren't repo files

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "board"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / "board" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_card(d: Path, cid: str, **fields) -> Path:
    import yaml
    card = {"id": cid}
    card.update(fields)
    p = d / f"{cid}.yml"
    p.write_text(yaml.safe_dump(card, sort_keys=False))
    return p


class BoardApiQueueWarnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load("board-api.py")

    def test_queue_warns_on_manual_type(self):
        card = {"id": "c-manual", "column": "backlog",
                "action": {"type": "manual"}}
        msg = self.mod.do_action(card, "queue", "tony")
        self.assertIn("starve", msg)
        self.assertIn("type=manual", msg)
        # queued but type NOT auto-flipped — semantics unchanged
        self.assertEqual(card["action"]["status"], "queued")
        self.assertEqual(card["action"]["type"], "manual")
        warns = [c for c in card["comms"]
                 if c["from"] == "chaba" and "starve" in c["text"]]
        self.assertEqual(len(warns), 1)

    def test_queue_dispatch_type_no_warn(self):
        for action in ({"type": "dispatch"}, {}):
            card = {"id": "c-ok", "column": "backlog", "action": action}
            msg = self.mod.do_action(card, "queue", "tony")
            self.assertEqual(msg, "queued — kanban-dispatch will claim it")
            self.assertEqual(card["action"]["type"], "dispatch")
            self.assertFalse(any("starve" in c["text"]
                                 for c in card["comms"]))

    def test_create_requeue_warns_on_manual(self):
        """on_exists:'queue' re-arm on a manual card warns too."""
        with tempfile.TemporaryDirectory() as td:
            self.mod.CARD_DIR = Path(td)
            _write_card(Path(td), "c-re",
                        column="done",
                        action={"type": "manual", "status": "done"})
            res = self.mod.do_create(
                {"id": "c-re", "title": "re", "on_exists": "queue"},
                "tony")
            self.assertIn("starve", res["message"])
            self.assertEqual(res["status"], "queued")

    def test_create_queue_true_warns_on_manual(self):
        with tempfile.TemporaryDirectory() as td:
            self.mod.CARD_DIR = Path(td)
            res = self.mod.do_create(
                {"id": "c-new", "title": "new", "queue": True,
                 "action": {"type": "manual"}}, "tony")
            self.assertIn("starve", res["message"])
            self.assertIn("queued", res["message"])
            import yaml
            saved = yaml.safe_load((Path(td) / "c-new.yml").read_text())
            self.assertEqual(saved["action"]["type"], "manual")
            self.assertTrue(any("starve" in c["text"]
                                for c in saved["comms"]))

    def test_requeue_updates_approved_executor_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            self.mod.CARD_DIR = Path(td)
            _write_card(Path(td), "c-re",
                        column="backlog",
                        action={"type": "dispatch", "status": "done"})
            self.mod.do_create(
                {"id": "c-re", "title": "re", "on_exists": "queue",
                 "action": {
                     "type": "dispatch",
                     "repo": "chaba",
                     "executor": "opencode",
                     "agent_profile": "branch-code-supervised-pilot",
                     "model": "litellm/claude-fable-5.1",
                     "target_host": "idc02",
                     "artifact": "evals/opencode-lane/out/ops-1039.json",
                     "lane": "free_lane",
                 }}, "tony")
            import yaml
            saved = yaml.safe_load((Path(td) / "c-re.yml").read_text())
            action = saved["action"]
            self.assertEqual(action["status"], "queued")
            self.assertEqual(action["executor"], "opencode")
            self.assertEqual(action["agent_profile"],
                             "branch-code-supervised-pilot")
            self.assertEqual(action["target_host"], "idc02")
            self.assertEqual(action["artifact"],
                             "evals/opencode-lane/out/ops-1039.json")


class DispatchSkipLogTest(unittest.TestCase):
    """kanban-dispatch prints a skip reason for a non-dispatch queued
    card instead of a silent continue."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("kanban-dispatch.py")

    def test_manual_queued_card_logs_skip(self):
        m = self.mod
        with tempfile.TemporaryDirectory() as td:
            m.CARD_DIR = Path(td)
            m.LOCK = Path(td) / "lock"
            _write_card(Path(td), "c-manual",
                        column="backlog",
                        action={"type": "manual", "status": "queued"})
            saved = (m.load_policy, m.overloaded, m.active_tasks,
                     m.push_capable)
            m.load_policy = lambda: {
                "kill_switch": str(Path(td) / "no-kill")}
            m.overloaded = lambda: False
            m.active_tasks = lambda: 0
            m.push_capable = lambda repo: True
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    m.main()
            finally:
                (m.load_policy, m.overloaded, m.active_tasks,
                 m.push_capable) = saved
            out = buf.getvalue()
            self.assertIn("c-manual", out)
            self.assertIn("skipped", out)
            self.assertIn("manual", out)


class InvariantQ1Test(unittest.TestCase):
    """board-invariants Q1 flags queued non-dispatch cards >24h old."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("board-invariants.py")

    def _run(self, cards: dict) -> dict:
        import yaml
        m = self.mod
        with tempfile.TemporaryDirectory() as td:
            m.CARD_DIR = Path(td)
            for cid, fields in cards.items():
                (Path(td) / f"{cid}.yml").write_text(
                    yaml.safe_dump({"id": cid, **fields}))
            return m.check_cards()

    def _ago(self, hours: float) -> str:
        return (dt.datetime.now()
                - dt.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")

    def test_starved_manual_card_flagged(self):
        finds = self._run({
            "c-starved": {"updated": self._ago(72),
                          "action": {"type": "manual",
                                     "status": "queued"}},
        })
        self.assertEqual(len(finds["Q1"]), 1)
        self.assertIn("c-starved", finds["Q1"][0])

    def test_fresh_queue_not_flagged(self):
        finds = self._run({
            "c-fresh": {"updated": self._ago(1),
                        "action": {"type": "manual",
                                   "status": "queued"}},
        })
        self.assertEqual(finds["Q1"], [])

    def test_dispatch_type_never_flagged(self):
        """A dispatch card queued >24h is a backlog/throughput question,
        not deterministic starvation — Q1 stays off it."""
        finds = self._run({
            "c-waiting": {"updated": self._ago(72),
                          "action": {"type": "dispatch",
                                     "status": "queued"}},
            "c-idle": {"updated": self._ago(72),
                       "action": {"type": "manual",
                                  "status": "idle"}},
        })
        self.assertEqual(finds["Q1"], [])


class FleetCapabilitiesTest(unittest.TestCase):
    """dispatch_repos.fleet_capabilities parses the runner_fleet prose
    into the declared claim surface; unsatisfiable_reasons is the
    shared no-runner verdict behind the queue/eval flags."""

    @classmethod
    def setUpClass(cls):
        cls.dr = _load("dispatch_repos.py")

    def test_fleet_parse(self):
        fleet = self.dr.fleet_capabilities()
        self.assertIn("idc03", fleet)
        self.assertIn("ada", fleet["idc03"]["labels"])
        self.assertIn("container", fleet["idc03"]["types"])
        self.assertIn("push:chaba", fleet["tony-dell"]["labels"])
        # macbook declares dispatch+script only (no podman)
        self.assertNotIn("container",
                         fleet["tony-macbook"]["types"])

    def test_ops0790_reason(self):
        """labels:[exec] + target_host:idc03 — the 2026-11-07 starve."""
        card = {"action": {"type": "dispatch", "status": "queued",
                           "labels": ["exec"], "target_host": "idc03",
                           "repo": "chaba"}}
        r = self.dr.unsatisfiable_reasons(card, local_host="nowhere")
        self.assertEqual(r, ["idc03 lacks labels ['exec']"])

    def test_satisfiable_is_quiet(self):
        for action in ({"type": "dispatch", "repo": "chaba"},
                       {"type": "dispatch", "labels": ["ada"]},
                       {"type": "dispatch", "target_host": "tony-dell",
                        "repo": "chaba"},
                       {"type": "dispatch", "executor": "manual"}):
            r = self.dr.unsatisfiable_reasons({"action": action},
                                              local_host="nowhere")
            self.assertEqual(r, [], action)

    def test_pin_and_executor_reasons(self):
        for action, want in (
                ({"target_host": "idc99"}, "names no declared runner"),
                ({"host": "ghost-host"}, "names no declared runner"),
                ({"executor": "gandalf"}, "no known executor"),
                ({"host": "tony-dell", "target_host": "idc03"},
                 "conflicts")):
            a = {"type": "dispatch", "status": "queued"}
            a.update(action)
            r = self.dr.unsatisfiable_reasons({"action": a},
                                              local_host="nowhere")
            self.assertTrue(any(want in x for x in r),
                            (action, r))

    def test_single_eligible_local_push_guard(self):
        """Pinned to this host, local probe fails -> deterministic push
        reason; remote single-candidate push is unprovable -> quiet."""
        a = {"type": "dispatch", "status": "queued",
             "target_host": "me", "repo": "chaba"}
        fleet = {"me": {"labels": set(), "types": {"dispatch"}}}
        r = self.dr.unsatisfiable_reasons(
            {"action": a}, fleet=fleet, local_host="me",
            push_probe=lambda repo: False)
        self.assertTrue(any("push guard" in x for x in r))
        r = self.dr.unsatisfiable_reasons(
            {"action": a}, fleet=fleet, local_host="other",
            push_probe=lambda repo: False)
        self.assertEqual(r, [])


class QueueUnclaimableWarnTest(unittest.TestCase):
    """board-api queue_unclaimable_warn + awaiting_action on queue."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("board-api.py")
        # a single-eligible card pinned to THIS host would run a real
        # `git push --dry-run` — pin the probe instead
        cls._push_probe = cls.mod.dr.push_probe
        cls.mod.dr.push_probe = lambda repo: {"pushable": True}

    @classmethod
    def tearDownClass(cls):
        cls.mod.dr.push_probe = cls._push_probe

    def test_queue_flags_unsatisfiable_labels(self):
        card = {"id": "c-exec", "column": "backlog",
                "action": {"type": "dispatch", "labels": ["exec"]}}
        msg = self.mod.do_action(card, "queue", "tony")
        self.assertIn("unclaimable", msg)
        self.assertTrue(card.get("awaiting_action"))
        hits = [c for c in card["comms"]
                if c["from"] == "chaba" and "unclaimable" in c["text"]]
        self.assertEqual(len(hits), 1)
        self.assertIn("exec", hits[0]["text"])

    def test_queue_flags_dead_target_host(self):
        card = {"id": "c-pindead", "column": "backlog",
                "action": {"type": "dispatch", "target_host": "idc99"}}
        msg = self.mod.do_action(card, "queue", "tony")
        self.assertIn("idc99", msg)
        self.assertTrue(card.get("awaiting_action"))

    def test_queue_satisfiable_no_flag(self):
        card = {"id": "c-ok", "column": "backlog",
                "action": {"type": "dispatch", "labels": ["ada"]}}
        msg = self.mod.do_action(card, "queue", "tony")
        self.assertEqual(msg, "queued — kanban-dispatch will claim it")
        self.assertIsNone(card.get("awaiting_action"))


class DispatchUnclaimableFlagTest(unittest.TestCase):
    """kanban-dispatch eval: fleet-unclaimable cards get comms +
    awaiting_action; satisfiable label misses get a per-host defer."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load("kanban-dispatch.py")

    def _run(self, *cards):
        import yaml
        m = self.mod
        with tempfile.TemporaryDirectory() as td:
            m.CARD_DIR = Path(td)
            m.LOCK = Path(td) / "lock"
            for cid, fields in cards:
                _write_card(Path(td), cid, **fields)
            saved = (m.load_policy, m.overloaded, m.active_tasks,
                     m.push_capable, m.start_pending)
            started = []
            m.load_policy = lambda: {
                "kill_switch": str(Path(td) / "k"),
                "state_file": str(Path(td) / "state.json")}
            m.overloaded = lambda: False
            m.active_tasks = lambda: 0
            m.push_capable = lambda repo: True
            m.start_pending = lambda p: (started.append(p.stem)
                                         or "started")
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    m.main()
            finally:
                (m.load_policy, m.overloaded, m.active_tasks,
                 m.push_capable, m.start_pending) = saved
            cards_out = {}
            for p in Path(td).glob("*.yml"):
                cards_out[p.stem] = yaml.safe_load(p.read_text())
            return buf.getvalue(), cards_out, started

    def test_unsatisfiable_labels_flagged(self):
        out, cards, started = self._run(
            ("c-exec", {"column": "backlog",
                        "action": {"type": "dispatch",
                                   "status": "queued",
                                   "labels": ["exec"]}}))
        self.assertIn("UNCLAIMABLE", out)
        c = cards["c-exec"]
        self.assertTrue(c.get("awaiting_action"))
        hits = [x for x in c.get("comms") or []
                if "unclaimable" in (x.get("text") or "")]
        self.assertEqual(len(hits), 1)
        self.assertEqual(started, [])

    def test_satisfiable_labels_get_defer_note(self):
        """ada is satisfiable (idc03) — this host's miss lands as a
        defer comms line, not the unclaimable flag."""
        out, cards, started = self._run(
            ("c-ada", {"column": "backlog",
                       "action": {"type": "dispatch",
                                  "status": "queued",
                                  "labels": ["ada"]}}))
        self.assertNotIn("UNCLAIMABLE", out)
        c = cards["c-ada"]
        self.assertIsNone(c.get("awaiting_action"))
        hits = [x for x in c.get("comms") or []
                if "defers: missing labels" in (x.get("text") or "")]
        self.assertEqual(len(hits), 1)
        self.assertEqual(started, [])

    def test_flag_debounced_on_second_pass(self):
        """An unchanged reason isn't re-logged every pass."""
        fields = {"column": "backlog",
                  "action": {"type": "dispatch", "status": "queued",
                             "labels": ["exec"]}}
        _, cards1, _ = self._run(("c-exec", dict(fields)))
        n1 = len(cards1["c-exec"].get("comms") or [])
        # second pass over the already-flagged card
        import yaml
        m = self.mod
        with tempfile.TemporaryDirectory() as td:
            m.CARD_DIR = Path(td)
            m.LOCK = Path(td) / "lock"
            (Path(td) / "c-exec.yml").write_text(
                yaml.safe_dump(cards1["c-exec"]))
            saved = (m.load_policy, m.overloaded, m.active_tasks,
                     m.push_capable)
            m.load_policy = lambda: {
                "kill_switch": str(Path(td) / "k"),
                "state_file": str(Path(td) / "state.json")}
            m.overloaded = lambda: False
            m.active_tasks = lambda: 0
            m.push_capable = lambda repo: True
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    m.main()
            finally:
                (m.load_policy, m.overloaded, m.active_tasks,
                 m.push_capable) = saved
            c2 = yaml.safe_load((Path(td) / "c-exec.yml").read_text())
        self.assertEqual(n1, len(c2.get("comms") or []))


if __name__ == "__main__":
    unittest.main()
