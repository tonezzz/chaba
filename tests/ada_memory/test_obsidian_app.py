"""Unit tests for apps/obsidian/server.py — auth-on-read (ADA_DEPLOY=public),
public bank-visibility filtering, and the /api/graph vault+MDDB merge.

MDDB is pointed at a dead port so graph tests exercise the vault-only
fallback without network. Run with the ada-pi venv:
  /home/tony/CascadeProjects/ada-pi/.venv/bin/python -m pytest tests/ada_memory/test_obsidian_app.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "apps/obsidian/server.py"


def load_server(vault: Path, deploy: str = "tailnet", api_key: str = ""):
    """Import server.py fresh with a patched env (module constants are
    read at import time)."""
    env = {
        "ADA_MEMORY_VAULT": str(vault),
        "ADA_VAULT_REPO": str(REPO),
        "ADA_MEMORY_MDDB_URL": "http://127.0.0.1:1/v1",
        "ADA_DEPLOY": deploy,
        "ADA_API_KEY": api_key,
    }
    name = f"obsidian_server_{deploy}_{bool(api_key)}_{abs(hash(str(vault))) % 99999}"
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location(name, SERVER)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def make_vault(td: str) -> Path:
    v = Path(td)
    for d in ("note", "personal/tony", "general", "github", "inbox"):
        (v / d).mkdir(parents=True, exist_ok=True)
    (v / "note/a.md").write_text(
        "---\nkey: note/a\nkind: fact\nsubject: gate-remote\n"
        "status: superseded\nsuperseded_by: note/b\n---\nold location\n")
    (v / "note/b.md").write_text(
        "---\nkey: note/b\nkind: fact\nsubject: gate-remote\n"
        "status: active\nsupersedes: note/a\n---\nnew location\n")
    (v / "note/c.md").write_text(
        "---\nkey: note/c\nkind: note\nstatus: active\n---\nunrelated\n")
    (v / "personal/tony/secret.md").write_text(
        "---\nkey: personal/secret\nkind: fact\nstatus: active\n---\nsecret\n")
    (v / "general/g.md").write_text(
        "---\nkey: general/g\nkind: fact\nstatus: active\n---\nhi\n")
    (v / "github/r.md").write_text(
        "---\nkey: github/r\nkind: note\nstatus: active\n---\nrepo assessment\n")
    return v


class TestHubSplit(unittest.TestCase):
    def test_oversized_subject_splits_into_month_subhubs(self):
        with tempfile.TemporaryDirectory() as td:
            v = Path(td)
            (v / "general").mkdir(parents=True)
            for i in range(45):
                month = "2026-08" if i % 2 else "2026-09"
                (v / f"general/s{i}.md").write_text(
                    f"---\nkey: general/s{i}\nkind: note\nstatus: active\n"
                    f"subject: mega\ndate: {month}-{i % 28 + 1:02d}\n---\nx\n")
            mod = load_server(v, deploy="tailnet")
            from fastapi.testclient import TestClient
            cli = TestClient(mod.app)
            g = cli.get("/api/graph").json()
            ids = {n["id"]: n for n in g["nodes"]}
            self.assertIn("subject:mega", ids)
            self.assertIn("subject:mega:2026-08", ids)
            self.assertIn("subject:mega:2026-09", ids)
            self.assertTrue(ids["subject:mega:2026-08"].get("subhub"))
            hub_links = [l for l in g["links"]
                         if l["type"] == "subject"
                         and l["target"] == "subject:mega"]
            self.assertEqual(hub_links, [])  # members link to sub-hubs only
            sub_links = [l for l in g["links"]
                         if l["type"] == "subject"
                         and l["target"].startswith("subject:mega:2")]
            self.assertEqual(len(sub_links), 45)


class _FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.request = None
    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            req = httpx.Request("POST", "http://x/v1/get")
            raise httpx.HTTPStatusError("err", request=req,
                                        response=httpx.Response(self.status_code))
    def json(self):
        return self._p


class _FakeClient:
    """httpx.AsyncClient stand-in: /get returns a canned doc."""
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json=None, **_):
        if url.endswith("/get"):
            return _FakeResp({
                "key": json["key"],
                "meta": {"kind": ["note"], "subject": ["gate-remote"],
                          "date": ["2026-09-18"], "written_by": ["devin-cli"]},
                "contentMd": "the remote lives in the hallway drawer",
            })
        return _FakeResp([])


class TestExport(unittest.TestCase):
    def _cli(self, td):
        v = make_vault(td)
        mod = load_server(v)
        from fastapi.testclient import TestClient
        return mod, v, TestClient(mod.app)

    def test_export_writes_vault_note(self):
        with tempfile.TemporaryDirectory() as td:
            mod, v, cli = self._cli(td)
            with mock.patch.object(mod.httpx, "AsyncClient", _FakeClient):
                r = cli.post("/api/export",
                             json={"id": "ada-ha-bank-note-tony:note/remote-loc"})
            self.assertEqual(r.status_code, 200, r.text)
            p = v / "note/remote-loc.md"
            self.assertTrue(p.exists())
            txt = p.read_text()
            self.assertIn("key: note/remote-loc", txt)
            self.assertIn("subject: gate-remote", txt)
            self.assertIn("hallway drawer", txt)

    def test_export_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            mod, v, cli = self._cli(td)
            with mock.patch.object(mod.httpx, "AsyncClient", _FakeClient):
                r = cli.post("/api/export",
                             json={"id": "ada-ha-bank-note-tony:note/a"})
            self.assertEqual(r.status_code, 409)  # note/a.md already exists

    def test_export_unknown_collection_404(self):
        with tempfile.TemporaryDirectory() as td:
            mod, v, cli = self._cli(td)
            with mock.patch.object(mod.httpx, "AsyncClient", _FakeClient):
                r = cli.post("/api/export", json={"id": "nope:x"})
            self.assertEqual(r.status_code, 404)

    def test_export_hidden_bank_404_in_public(self):
        with tempfile.TemporaryDirectory() as td:
            mod, v, cli = self._cli(td)
            mod2 = load_server(v, deploy="public", api_key="k")
            from fastapi.testclient import TestClient
            cli2 = TestClient(mod2.app)
            with mock.patch.object(mod2.httpx, "AsyncClient", _FakeClient):
                # note bank is not public: true -> hidden in public mode
                r = cli2.post("/api/export",
                              json={"id": "ada-ha-bank-note-tony:note/a"},
                              headers={"X-API-Key": "k"})
            self.assertEqual(r.status_code, 404)


class TestPromote(unittest.TestCase):
    def test_promote_moves_inbox_note(self):
        with tempfile.TemporaryDirectory() as td:
            v = make_vault(td)
            (v / "inbox/draft.md").write_text(
                "---\nkey: draft\nstatus: draft\n---\nidea\n")
            mod = load_server(v)
            from fastapi.testclient import TestClient
            r = TestClient(mod.app).post(
                "/api/promote", json={"path": "inbox/draft.md",
                                      "bank": "general"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertFalse((v / "inbox/draft.md").exists())
            self.assertTrue((v / "general/draft.md").exists())

    def test_promote_rejects_non_inbox(self):
        with tempfile.TemporaryDirectory() as td:
            v = make_vault(td)
            mod = load_server(v)
            from fastapi.testclient import TestClient
            r = TestClient(mod.app).post(
                "/api/promote", json={"path": "note/b.md", "bank": "general"})
            self.assertEqual(r.status_code, 400)

    def test_promote_unknown_bank_404(self):
        with tempfile.TemporaryDirectory() as td:
            v = make_vault(td)
            (v / "inbox/draft.md").write_text("---\nkey: d\n---\nx\n")
            mod = load_server(v)
            from fastapi.testclient import TestClient
            r = TestClient(mod.app).post(
                "/api/promote", json={"path": "inbox/draft.md",
                                      "bank": "nope"})
            self.assertEqual(r.status_code, 404)


class TestDeployGuard(unittest.TestCase):
    def test_public_without_key_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as td:
            v = make_vault(td)
            with self.assertRaises(SystemExit):
                load_server(v, deploy="public", api_key="")


class TestTailnet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        vault = make_vault(cls._td.name)
        cls.mod = load_server(vault, deploy="tailnet")
        from fastapi.testclient import TestClient
        cls.cli = TestClient(cls.mod.app)

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def test_tree_open_without_key(self):
        r = self.cli.get("/api/tree")
        self.assertEqual(r.status_code, 200)
        self.assertIn("personal/tony", r.json()["banks"])
        self.assertIn("note", r.json()["banks"])

    def test_note_read_open(self):
        r = self.cli.get("/api/note", params={"path": "personal/tony/secret.md"})
        self.assertEqual(r.status_code, 200)

    def test_graph_vault_only_fallback(self):
        r = self.cli.get("/api/graph")
        self.assertEqual(r.status_code, 200)
        g = r.json()
        self.assertFalse(g["sources"]["mddb"])
        self.assertIn("warning", g)
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("ada-ha-bank-note-tony:note/a", ids)
        self.assertIn("ada-ha-bank-personal-tony:personal/secret", ids)

    def test_graph_supersedes_edge_deduped(self):
        g = self.cli.get("/api/graph").json()
        sup = [l for l in g["links"] if l["type"] == "supersedes"]
        self.assertEqual(len(sup), 1)
        self.assertEqual(sup[0]["source"], "ada-ha-bank-note-tony:note/a")
        self.assertEqual(sup[0]["target"], "ada-ha-bank-note-tony:note/b")

    def test_graph_subject_hub(self):
        g = self.cli.get("/api/graph").json()
        ids = {n["id"]: n for n in g["nodes"]}
        self.assertIn("subject:gate-remote", ids)
        self.assertEqual(ids["subject:gate-remote"]["hub"], "subject")
        hub_edges = [l for l in g["links"]
                     if l["type"] == "subject" and l["target"] == "subject:gate-remote"]
        self.assertEqual(len(hub_edges), 2)

    def test_graph_inbox_sync_state(self):
        g = self.cli.get("/api/graph").json()
        by_sync = {n["id"]: n.get("sync") for n in g["nodes"]}
        self.assertEqual(by_sync["ada-ha-bank-note-tony:note/a"], "vault_only")

    def test_graph_status_filter(self):
        g = self.cli.get("/api/graph", params={"status": "active"}).json()
        statuses = {n.get("status") for n in g["nodes"] if not n.get("hub")}
        self.assertNotIn("superseded", statuses)


class TestPublic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        vault = make_vault(cls._td.name)
        cls.mod = load_server(vault, deploy="public", api_key="k")
        from fastapi.testclient import TestClient
        cls.cli = TestClient(cls.mod.app)
        cls.auth = {"X-API-Key": "k"}

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def test_reads_require_key(self):
        self.assertEqual(self.cli.get("/api/tree").status_code, 401)
        self.assertEqual(self.cli.get("/api/status").status_code, 401)
        self.assertEqual(self.cli.get("/api/graph").status_code, 401)
        self.assertEqual(
            self.cli.get("/api/note", params={"path": "github/r.md"}).status_code,
            401)

    def test_tree_only_public_banks(self):
        r = self.cli.get("/api/tree", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.json()["banks"].keys()), ["github"])

    def test_hidden_note_is_404_not_403(self):
        r = self.cli.get("/api/note", headers=self.auth,
                         params={"path": "personal/tony/secret.md"})
        self.assertEqual(r.status_code, 404)

    def test_status_reports_hidden_count(self):
        s = self.cli.get("/api/status", headers=self.auth).json()
        self.assertEqual(s["deploy"], "public")
        self.assertGreater(s["hidden_banks"], 0)
        self.assertNotIn("personal", s["counts"])

    def test_graph_drops_hidden_banks_and_edges(self):
        g = self.cli.get("/api/graph", headers=self.auth).json()
        ids = {n["id"] for n in g["nodes"]}
        self.assertEqual(ids, {"ada-ha-bank-github:github/r"})
        # no edges may reference hidden collections
        self.assertEqual(g["links"], [])
        self.assertGreater(g["stats"]["hidden_banks"], 0)


if __name__ == "__main__":
    unittest.main()
