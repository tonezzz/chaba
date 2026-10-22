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


if __name__ == "__main__":
    unittest.main()
