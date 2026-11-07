"""Tests for runner-agent.reconcile_pass — the OPS-1071 zombie-claim
sweeper. A claim POST that commits server-side but loses its response
leaves action.status=running with no unit and no state entry; the next
pass must adopt a live unit or restart the task under the same claim.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/board/runner-agent.py"
sys.path.insert(0, str(REPO / "scripts" / "board"))


def _load():
    spec = importlib.util.spec_from_file_location("runner_agent_recon",
                                                  SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(rc=0, out="", err=""):
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _card(cid="zombie-card", **action_kw):
    a = {"type": "dispatch", "status": "running", "runner": "testhost"}
    a.update(action_kw)
    return {"id": cid, "title": cid, "action": a}


class ReconcilePassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def setUp(self):
        m = self.mod
        self._saved = {k: getattr(m, k) for k in ("HOST", "CAP")}
        self.m = m
        m.HOST = "testhost"
        m.CAP = 3
        self.posts = []
        self.units_out = ""
        m.api = lambda path, body=None: (
            self.posts.append((path, body)) or
            ({"cards": self._cards} if path == "/cards" and body is None
             else {}))
        m.sh = lambda argv, **kw: _proc(
            0, self.units_out if "list-units" in " ".join(argv) else "")
        self._cards = []
        self.started = []
        m.start_task = lambda card, typ: (
            self.started.append(card["id"]) or ("devin-task-x-1", "x-1", ""))

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.m, k, v)

    def test_adopts_live_unit_for_untracked_claim(self):
        self._cards = [_card()]
        self.units_out = ("devin-task-zombie-card-1700000000.service "
                          "loaded active running x\n")
        st = {}
        self.assertTrue(self.m.reconcile_pass(st))
        ent = st["zombie-card"]
        self.assertEqual(ent["unit"],
                         "devin-task-zombie-card-1700000000")
        self.assertEqual(ent["tid"], "zombie-card-1700000000")
        self.assertTrue(ent["adopted"])
        self.assertEqual(self.started, [])

    def test_restarts_when_no_unit_exists(self):
        self._cards = [_card()]
        self.units_out = ""
        st = {}
        self.assertTrue(self.m.reconcile_pass(st))
        self.assertEqual(self.started, ["zombie-card"])
        ent = st["zombie-card"]
        self.assertTrue(ent["restarted"])
        self.assertEqual(ent["unit"], "devin-task-x-1")

    def test_restart_failure_releases_claim(self):
        self._cards = [_card()]
        self.units_out = ""
        self.m.start_task = lambda c, t: ("", "", "no worktree")
        st = {}
        self.m.reconcile_pass(st)
        self.assertNotIn("zombie-card", st)
        fin = [b for p, b in self.posts
               if p == "/action" and (b or {}).get("do") == "finish"]
        self.assertTrue(fin)
        self.assertFalse(fin[0]["ok"])
        self.assertIn("zombie claim", fin[0]["result"])

    def test_kanban_dispatch_claim_untouched(self):
        self._cards = [_card(task_id="20261107-000000-abc",
                             )]
        self._cards[0]["claim"] = {"session": "20261107-000000-abc"}
        self.units_out = ("devin-task-zombie-card-1700000000.service "
                          "loaded active running x\n")
        st = {}
        self.assertFalse(self.m.reconcile_pass(st))
        self.assertEqual(st, {})
        self.assertEqual(self.started, [])

    def test_other_host_and_state_entries_untouched(self):
        self._cards = [
            _card("other-host-card", runner="idc02"),
            _card("queued-card", status="queued", runner=None),
        ]
        st = {"mine": {"unit": "u"}}
        self.units_out = ""
        self.assertFalse(self.m.reconcile_pass(st))
        self.assertEqual(list(st), ["mine"])
        self.assertEqual(self.started, [])

    def test_cap_blocks_restart_but_not_adoption(self):
        self._cards = [_card("cap-card"), _card("adopt-card")]
        # adopt-card has a unit; cap-card doesn't and st is at CAP
        self.m.CAP = 1
        st = {"existing": {"unit": "u"}}
        self.units_out = ("devin-task-adopt-card-1700000001.service "
                          "loaded active running x\n")
        self.m.reconcile_pass(st)
        self.assertIn("adopt-card", st)
        self.assertNotIn("cap-card", st)
        self.assertEqual(self.started, [])


if __name__ == "__main__":
    unittest.main()
