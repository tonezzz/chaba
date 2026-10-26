"""Unit tests for the project rollup (card board-project-rollup):

- scripts/lib/projects.py — `project: <slug>` tag + `project:` field
  extraction and the per-project rollup (stage, by_column, next_action)
- scripts/board/board-api.py — GET /cards?project=… / ?projects view
  functions (cards_project_view, cms_project_stage) with _mddb_post faked

No network, no repo writes — the view functions are pure over a payload.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


projects = _load("projects.py", "scripts/lib/projects.py")
api = _load("board-api.py", "scripts/board/board-api.py")


class CardProjectsTest(unittest.TestCase):
    def test_tag_forms(self):
        c = {"tags": ["project: foo-bar", "project:baz", "kanban"]}
        self.assertEqual(projects.card_projects(c), ["foo-bar", "baz"])

    def test_tag_case_and_space(self):
        c = {"tags": ["Project: FOO"]}
        self.assertEqual(projects.card_projects(c), ["foo"])

    def test_field_str_and_list(self):
        self.assertEqual(projects.card_projects({"project": "X"}), ["x"])
        self.assertEqual(projects.card_projects(
            {"project": ["a", "b"]}), ["a", "b"])

    def test_field_and_tag_union(self):
        c = {"project": "one", "tags": ["project: two", "project:one"]}
        self.assertEqual(projects.card_projects(c), ["one", "two"])

    def test_no_project(self):
        self.assertEqual(projects.card_projects({"tags": ["x"]}), [])
        self.assertEqual(projects.card_projects({}), [])


def _card(cid, col="backlog", **kw):
    return {"id": cid, "title": cid, "column": col, **kw}


class RollupTest(unittest.TestCase):
    def setUp(self):
        self.cards = [
            _card("a1", "doing", tags=["project: alpha"],
                  priority="high", updated="2026-10-20"),
            _card("a2", "backlog", tags=["project:alpha"],
                  updated="2026-10-22"),
            _card("b1", "done", project="beta", updated="2026-10-10"),
            _card("b2", "done", project="beta", updated="2026-10-12"),
            _card("c1", "backlog", tags=["unrelated"]),
        ]

    def test_groups(self):
        rows = {p["slug"]: p for p in projects.project_rollup(self.cards)}
        self.assertEqual(set(rows), {"alpha", "beta"})
        self.assertEqual(rows["alpha"]["n"], 2)
        self.assertEqual(rows["alpha"]["by_column"],
                         {"doing": 1, "backlog": 1})

    def test_stage_from_columns(self):
        rows = {p["slug"]: p for p in projects.project_rollup(self.cards)}
        self.assertEqual(rows["alpha"]["stage"], "in flight")
        self.assertEqual(rows["alpha"]["stage_source"], "columns")
        self.assertEqual(rows["beta"]["stage"], "done")

    def test_next_action_prefers_open_ask(self):
        self.cards[1]["requests"] = [
            {"id": "r1", "ask": "which lane?", "status": "open"}]
        row = next(p for p in projects.project_rollup(self.cards)
                   if p["slug"] == "alpha")
        self.assertEqual(row["open"], 1)
        self.assertEqual(row["next_action"]["kind"], "ask")
        self.assertEqual(row["next_action"]["text"], "which lane?")

    def test_next_action_running_then_top_card(self):
        rows = {p["slug"]: p for p in projects.project_rollup(self.cards)}
        # no asks: 'a1' is doing but has no action.status — doing column wins
        self.assertEqual(rows["alpha"]["next_action"]["id"], "a1")
        self.assertIsNone(rows["beta"]["next_action"])  # all done

    def test_open_work_sorts_first(self):
        rows = projects.project_rollup(self.cards)
        self.assertEqual(rows[0]["slug"], "alpha")
        self.assertEqual(rows[-1]["slug"], "beta")

    def test_member_card_fields(self):
        rows = {p["slug"]: p for p in projects.project_rollup(self.cards)}
        a1 = next(c for c in rows["alpha"]["cards"] if c["id"] == "a1")
        self.assertEqual(a1["column"], "doing")
        self.assertEqual(a1["priority"], "high")

    def test_matches(self):
        self.assertTrue(projects.matches(self.cards[0], "ALPHA"))
        self.assertFalse(projects.matches(self.cards[0], "beta"))


class ApiViewTest(unittest.TestCase):
    PAYLOAD = {
        "generated": "2026-10-26 12:00",
        "cards": [
            _card("a1", "doing", tags=["project: alpha"]),
            _card("a2", "backlog", project="alpha"),
            _card("b1", "done", tags=["project:beta"]),
            _card("c1"),
        ],
    }

    def setUp(self):
        self._real = api._mddb_post
        api._mddb_post = lambda *a, **k: {
            "contentMd": "goal: ship\nstage: alpha\nnext: soak"}

    def tearDown(self):
        api._mddb_post = self._real

    def test_project_view(self):
        code, obj = api.cards_project_view(
            self.PAYLOAD, {"project": ["alpha"]})
        self.assertEqual(code, 200)
        self.assertEqual(obj["project"]["slug"], "alpha")
        self.assertEqual(obj["project"]["stage"], "alpha")
        self.assertEqual(obj["project"]["stage_source"], "cms")
        self.assertEqual(len(obj["cards"]), 2)

    def test_project_view_no_cards(self):
        code, obj = api.cards_project_view(
            self.PAYLOAD, {"project": ["alpha"], "cards": ["0"]})
        self.assertEqual(code, 200)
        self.assertNotIn("cards", obj)

    def test_unknown_slug_404_with_known(self):
        code, obj = api.cards_project_view(
            self.PAYLOAD, {"project": ["nope"]})
        self.assertEqual(code, 404)
        self.assertIn("alpha", obj["known"])

    def test_projects_list(self):
        code, obj = api.cards_project_view(
            self.PAYLOAD, {"projects": [""]})
        self.assertEqual(code, 200)
        self.assertEqual({p["slug"] for p in obj["projects"]},
                         {"alpha", "beta"})

    def test_meta_stage_wins_over_body(self):
        api._mddb_post = lambda *a, **k: {
            "meta": {"stage": ["beta"]}, "contentMd": "stage: alpha"}
        code, obj = api.cards_project_view(
            self.PAYLOAD, {"project": ["alpha"]})
        self.assertEqual(obj["project"]["stage"], "beta")

    def test_mddb_down_degrades_to_columns(self):
        def boom(*a, **k):
            raise OSError("mddb down")
        api._mddb_post = boom
        code, obj = api.cards_project_view(
            self.PAYLOAD, {"project": ["alpha"]})
        self.assertEqual(code, 200)
        self.assertEqual(obj["project"]["stage"], "in flight")
        self.assertEqual(obj["project"]["stage_source"], "columns")

    def test_pre_feature_payload_recomputes(self):
        # a cards.json rendered before the feature has no `projects` key —
        # the view recomputes rollups from `cards` instead of 500ing
        self.assertNotIn("projects", self.PAYLOAD)
        code, _ = api.cards_project_view(
            self.PAYLOAD, {"projects": ["1"]})
        self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
