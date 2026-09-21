"""Unit tests for apps/secrets/server.py — slot read/write scripts run
locally (SECRETS_LOCAL_HOST=test trickery avoided by calling the remote
scripts directly on tmp files), parity logic, vault roundtrip, auth gates.

Run with the ada-pi venv (fastapi + cryptography needed):
  /home/tony/CascadeProjects/ada-pi/.venv/bin/python -m pytest tests/ada_memory/test_secrets_console.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "apps/secrets/server.py"


def load_server(env_extra: dict | None = None):
    env = {"ADA_DEPLOY": "tailnet"}
    env.update(env_extra or {})
    name = f"secrets_server_{abs(hash(json.dumps(env_extra, sort_keys=True, default=str))) % 99999}"
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location(name, SERVER)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def run_script(script: str, args: list[str], stdin: str = "") -> dict:
    r = subprocess.run(["python3", "-c", script] + args,
                       input=stdin, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


mod = load_server()


class TestSlotRead(unittest.TestCase):
    def test_var_read(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write('A=1\nGEMINI_API_KEY="sekret-123"\nB=x\n')
            f.flush()
            r = run_script(mod._REMOTE_READ, [f.name, "GEMINI_API_KEY", "var"])
            self.assertTrue(r["present"])
            self.assertEqual(r["len"], len("sekret-123"))

    def test_var_read_missing_file_and_var(self):
        r = run_script(mod._REMOTE_READ, ["/nonexistent.env", "X", "var"])
        self.assertFalse(r["present"])
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("A=1\n")
            f.flush()
            r = run_script(mod._REMOTE_READ, [f.name, "NOPE", "var"])
            self.assertFalse(r["present"])

    def test_file_read_hashes_whole_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write('{"key": "abc"}')
            f.flush()
            r = run_script(mod._REMOTE_READ, [f.name, "", "file"])
            self.assertTrue(r["present"])
            import hashlib
            self.assertEqual(r["fingerprint"],
                             hashlib.sha256(b'{"key": "abc"}').hexdigest()[:12])

    def test_unit_read_quoted_environment(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write('[Service]\nEnvironment="GEMINI_API_KEY=unit-secret-9"\n')
            f.flush()
            r = run_script(mod._REMOTE_READ, [f.name, "GEMINI_API_KEY", "unit"])
            self.assertTrue(r["present"])
            self.assertEqual(r["len"], len("unit-secret-9"))


class TestSlotWrite(unittest.TestCase):
    def test_var_write_replaces_and_keeps_bak(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("A=1\nKEY=old\nB=x\n")
            f.flush()
            run_script(mod._REMOTE_WRITE, [f.name, "KEY", "var"], "new-val")
            self.assertIn("KEY=new-val", open(f.name).read())
            self.assertIn("A=1", open(f.name).read())
            import glob
            self.assertTrue(glob.glob(f.name + ".bak-*"))
            self.assertEqual(oct(os.stat(f.name).st_mode & 0o777), "0o600")

    def test_var_write_appends_when_absent(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("A=1\n")
            f.flush()
            run_script(mod._REMOTE_WRITE, [f.name, "NEWVAR", "var"], "v9")
            self.assertIn("NEWVAR=v9", open(f.name).read())

    def test_unit_write_rewrites_inside_environment(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write('[Service]\nEnvironment="GEMINI_API_KEY=old"\n')
            f.flush()
            run_script(mod._REMOTE_WRITE, [f.name, "GEMINI_API_KEY", "unit"], "new9")
            self.assertIn('Environment="GEMINI_API_KEY=new9"',
                          open(f.name).read())

    def test_file_write_replaces_whole_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("old")
            f.flush()
            run_script(mod._REMOTE_WRITE, [f.name, "", "file"], '{"new": 1}')
            self.assertEqual(open(f.name).read(), '{"new": 1}')


class TestParity(unittest.TestCase):
    def test_parity_states(self):
        s = lambda fp=None, p=True, e=None: {"present": p, "fingerprint": fp, "error": e}
        self.assertEqual(mod._parity([s("a"), s("a")]), "consistent")
        self.assertEqual(mod._parity([s("a"), s("b")]), "DRIFT")
        self.assertEqual(mod._parity([s(p=False), s(p=False)]), "empty")


class TestVault(unittest.TestCase):
    def test_vault_roundtrip_and_no_secret_in_list(self):
        with tempfile.TemporaryDirectory() as td:
            env = {"SECRETS_VAULT": f"{td}/v.enc",
                   "SECRETS_VAULT_KEY_FILE": f"{td}/key",
                   "SECRETS_CONSOLE_API_KEY": "k",
                   "SECRETS_VAULT_REPLICA": ""}
            m = load_server(env)
            from fastapi.testclient import TestClient
            cli = TestClient(m.app)
            r = cli.post("/api/vault", json={"title": "router",
                                             "username": "admin",
                                             "secret": "pw123"},
                         headers={"X-API-Key": "k"})
            self.assertEqual(r.status_code, 200)
            eid = r.json()["id"]
            listed = cli.get("/api/vault").json()["entries"][0]
            self.assertNotIn("secret", listed)
            rev = cli.post(f"/api/vault/{eid}/reveal",
                           headers={"X-API-Key": "k"})
            self.assertEqual(rev.json()["secret"], "pw123")
            # encrypted at rest
            self.assertNotIn(b"pw123", Path(f"{td}/v.enc").read_bytes())
            # key file is 600
            self.assertEqual(oct(os.stat(f"{td}/key").st_mode & 0o777), "0o600")

    def test_writes_require_key(self):
        with tempfile.TemporaryDirectory() as td:
            m = load_server({"SECRETS_VAULT": f"{td}/v.enc",
                             "SECRETS_VAULT_KEY_FILE": f"{td}/key",
                             "SECRETS_CONSOLE_API_KEY": "k"})
            from fastapi.testclient import TestClient
            cli = TestClient(m.app)
            r = cli.post("/api/vault", json={"title": "x"})
            self.assertEqual(r.status_code, 401)

    def test_readonly_when_no_key(self):
        m = load_server({})
        from fastapi.testclient import TestClient
        cli = TestClient(m.app)
        self.assertTrue(cli.get("/api/health").json()["readonly"])
        r = cli.post("/api/vault", json={"title": "x"})
        self.assertEqual(r.status_code, 503)


class TestDeployGuard(unittest.TestCase):
    def test_public_refuses(self):
        with self.assertRaises(SystemExit):
            load_server({"ADA_DEPLOY": "public"})


if __name__ == "__main__":
    unittest.main()
