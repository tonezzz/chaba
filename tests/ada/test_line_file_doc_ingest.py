"""Unit tests for the line-file-doc-ingest drop staged under
integrations/ada-pi/ (card line-file-doc-ingest, 2026-10-13).

Two halves:

- doc_read (backend/tools.d/doc_read.py) — loaded standalone with a
  stubbed backend.gemini_pool + google.genai types, exercised against a
  fixture PDF in a tmp archive: URL/path resolution is confined to the
  media roots, run() passes the bytes to the pool as an inline part and
  returns the structured result.

- line_relay patch — applied to a copy of the live ada-pi source
  (ADA_PI env or ~/CascadeProjects/ada-pi), compiled, and its
  handle_event driven with a fake file/video/sticker LINE event to
  prove archive + journal + synthetic turn + delivery. Skips when no
  ada-pi checkout is reachable (the patch is what ships, not the file).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import types as pytypes
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-pi"
DOC_READ = DROP / "backend" / "tools.d" / "doc_read.py"
PATCH = DROP / "backend" / "line_relay.file-doc-ingest.patch"
ADA_PI = Path(os.environ.get("ADA_PI",
                             str(Path.home() / "CascadeProjects/ada-pi")))

PDF = (b"%PDF-1.1\n"
       b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF\n")


# ---------------------------------------------------------------- doc_read

def _load_doc_read(tmp_path, monkeypatch):
    """Import doc_read standalone with the two external seams stubbed."""
    monkeypatch.setenv("LINE_MEDIA_ARCHIVE_DIR", str(tmp_path / "arch"))
    monkeypatch.setenv("LINE_IMG_CACHE_DIR", str(tmp_path / "img"))
    (tmp_path / "arch").mkdir(exist_ok=True)
    (tmp_path / "img").mkdir(exist_ok=True)

    calls = []

    async def _generate(model, contents, config=None, client=None,
                        timeout=None, tool="", mddb=None, session_id=""):
        calls.append({"model": model, "contents": contents,
                      "tool": tool, "timeout": timeout,
                      "session_id": session_id})
        return SimpleNamespace(text="BK123 — departs BKK 10:40")

    pool = pytypes.ModuleType("backend.gemini_pool")
    pool.generate = _generate

    class QuotaExhaustedError(RuntimeError):
        pass
    pool.QuotaExhaustedError = QuotaExhaustedError
    pool.is_quota_error = lambda e: False

    backend = pytypes.ModuleType("backend")
    backend.__path__ = []  # mark as package
    backend.gemini_pool = pool

    gtypes = pytypes.ModuleType("google.genai.types")

    class _Part:
        def __init__(self, data, mime_type):
            self.inline_data = {"data": data, "mime_type": mime_type}

        @classmethod
        def from_bytes(cls, data=None, mime_type=None):
            return cls(data, mime_type)

    gtypes.Part = _Part
    ggenai = pytypes.ModuleType("google.genai")
    ggenai.types = gtypes
    gpkg = pytypes.ModuleType("google")
    gpkg.genai = ggenai

    # Stubs must outlive exec_module — run() re-imports google.genai lazily
    # at call time. monkeypatch.setitem reverts them at test end.
    monkeypatch.setitem(sys.modules, "backend", backend)
    monkeypatch.setitem(sys.modules, "backend.gemini_pool", pool)
    monkeypatch.setitem(sys.modules, "google", gpkg)
    monkeypatch.setitem(sys.modules, "google.genai", ggenai)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    spec = importlib.util.spec_from_file_location(
        "tools_d.doc_read", DOC_READ)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, calls


def _runner():
    return SimpleNamespace(
        context=SimpleNamespace(mddb=None, session_id="sess-1"))


def _arch_file(tmp_path, chat="Uxxxx", name="m1.pdf", data=PDF):
    d = tmp_path / "arch" / chat
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


class TestDocReadResolve:
    def test_arch_url_and_host_relative(self, tmp_path, monkeypatch):
        mod, _ = _load_doc_read(tmp_path, monkeypatch)
        f = _arch_file(tmp_path)
        for spec in (f"https://img.test/relay-img/arch/Uxxxx/{f.name}",
                     f"/relay-img/arch/Uxxxx/{f.name}"):
            p, err = mod._resolve(spec)
            assert err is None and p == f

    def test_relative_chat_file_and_nonce(self, tmp_path, monkeypatch):
        mod, _ = _load_doc_read(tmp_path, monkeypatch)
        f = _arch_file(tmp_path)
        p, err = mod._resolve(f"Uxxxx/{f.name}")
        assert err is None and p == f
        n = tmp_path / "img" / "abc123"
        n.write_bytes(b"\x89PNG")
        p, err = mod._resolve("abc123")
        assert err is None and p == n
        p, err = mod._resolve("/relay-img/abc123")
        assert err is None and p == n

    def test_confinement(self, tmp_path, monkeypatch):
        mod, _ = _load_doc_read(tmp_path, monkeypatch)
        _arch_file(tmp_path)
        for bad in ("/etc/passwd",
                    str(tmp_path / "outside.pdf"),
                    "/relay-img/arch/../../etc/passwd",
                    "Uxxxx/../../etc/passwd",
                    "https://evil.example/elsewhere/x.pdf"):
            p, err = mod._resolve(bad)
            assert p is None and err, bad

    def test_missing_is_honest_error(self, tmp_path, monkeypatch):
        mod, _ = _load_doc_read(tmp_path, monkeypatch)
        p, err = mod._resolve("/relay-img/arch/Uxxxx/nope.pdf")
        assert p is None and "no archived file" in err


class TestDocReadRun:
    def test_extract_inline_part(self, tmp_path, monkeypatch):
        mod, calls = _load_doc_read(tmp_path, monkeypatch)
        f = _arch_file(tmp_path)
        out = asyncio.run(mod.run(
            _runner(),
            path_or_url=f"https://img.test/relay-img/arch/Uxxxx/{f.name}",
            prompt="booking refs and flight legs"))
        assert out["ok"] is True
        assert "BK123" in out["text"]
        assert out["name"] == "m1.pdf" and out["mime"] == "application/pdf"
        contents = calls[0]["contents"]
        part = contents[0]
        assert part.inline_data["data"] == PDF
        assert part.inline_data["mime_type"] == "application/pdf"
        assert contents[1] == "booking refs and flight legs"
        assert calls[0]["tool"] == "doc_read"

    def test_missing_arg_and_empty_file(self, tmp_path, monkeypatch):
        mod, _ = _load_doc_read(tmp_path, monkeypatch)
        out = asyncio.run(mod.run(_runner()))
        assert out["ok"] is False and "path_or_url" in out["error"]
        f = _arch_file(tmp_path, name="m2.pdf", data=b"")
        out = asyncio.run(mod.run(
            _runner(), path_or_url=f"Uxxxx/{f.name}"))
        assert out["ok"] is False and "empty" in out["error"]

    def test_oversize_cap(self, tmp_path, monkeypatch):
        mod, calls = _load_doc_read(tmp_path, monkeypatch)
        f = _arch_file(tmp_path, name="big.pdf")
        monkeypatch.setattr(mod, "MAX_BYTES", 10)
        out = asyncio.run(mod.run(_runner(), path_or_url=f"Uxxxx/{f.name}"))
        assert out["ok"] is False and "MiB" in out["error"]
        assert not calls  # never billed the pool for a refused read

    def test_generate_failure_is_spoken_error(self, tmp_path, monkeypatch):
        mod, _ = _load_doc_read(tmp_path, monkeypatch)
        _arch_file(tmp_path)

        async def _boom(**kw):
            raise RuntimeError("pool down")
        mod.gemini_pool.generate = _boom
        out = asyncio.run(mod.run(
            _runner(), path_or_url="/relay-img/arch/Uxxxx/m1.pdf"))
        assert out["ok"] is False and "unavailable" in out["error"]


# ------------------------------------------------------------- manifest etc

def test_manifest_and_guide_parse():
    m = yaml.safe_load(
        (DROP / "backend/tools.d/manifest.doc_read.yml").read_text())
    t = m["tools"]["doc_read"]
    assert t["module"] == "doc_read" and t["policy"] == "read"
    assert t["secondary_allowed"] is True
    g = yaml.safe_load(
        (DROP / "backend/tool_guide.doc_read.yml").read_text())
    assert "doc_read" in g
    s = yaml.safe_load(
        (DROP / "tests/scenarios-live/doc_read.yaml").read_text())
    assert s["turns"][0]["expect"]["calls_any"] == ["doc_read"]


def test_declaration_meets_surface_caps():
    """ssot.tool-surface.yml: desc <=300 chars (model-facing blurb)."""
    spec = importlib.util.spec_from_file_location("tools_d.dr2", DOC_READ)
    # AST-parse instead of exec so no stubs are needed for a decl check.
    import ast
    tree = ast.parse(DOC_READ.read_text())
    decl = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "DECLARATION"
                        for t in n.targets))
    d = ast.literal_eval(decl.value)
    assert d["name"] == "doc_read"
    assert len(d["description"]) <= 300
    assert d["parameters"]["required"] == ["path_or_url"]


def test_persons_profile_lists_doc_read():
    data = yaml.safe_load(
        (REPO / "docs/ssot/apps/ssot.apps.ada-persons.yml").read_text())
    assert "doc_read" in data["persons"]["kk"]["tools"]["include"]
    for prof in ("kk-cms-only", "kk-parity"):
        assert "doc_read" in data["bench_profiles"][prof]["include"], prof


# --------------------------------------------------------------- relay patch

@pytest.mark.skipif(
    not (ADA_PI / "backend/line_relay.py").is_file(),
    reason="no ada-pi checkout to apply the patch against")
class TestRelayPatch:
    def _patched_module(self, tmp_path, monkeypatch):
        src = tmp_path / "backend"
        src.mkdir()
        target = src / "line_relay.py"
        target.write_bytes(
            (ADA_PI / "backend/line_relay.py").read_bytes())
        r = subprocess.run(
            ["git", "apply", "--check", str(PATCH)],
            cwd=tmp_path, capture_output=True, text=True)
        assert r.returncode == 0, f"patch no longer applies: {r.stderr}"
        subprocess.run(["git", "apply", str(PATCH)],
                       cwd=tmp_path, check=True)
        monkeypatch.setenv("LINE_MEDIA_ARCHIVE_DIR",
                           str(tmp_path / "arch"))
        monkeypatch.setenv("LINE_IMG_CACHE_DIR", str(tmp_path / "img"))
        monkeypatch.setenv("LINE_PUBLIC_IMG_BASE",
                           "https://img.test/relay-img")
        monkeypatch.setenv("LINE_ALLOWED_USER_IDS", "U1")
        monkeypatch.setenv("LINE_USER_CALLERS", "U1:user-kk")
        monkeypatch.setenv("LINE_NAME_BACKENDS", "ada:ws://lane")
        spec = importlib.util.spec_from_file_location(
            "line_relay_patched", target)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _relay(self, mod, tmp_path):
        relay = mod.LineRelay()
        sent = {"turns": [], "msgs": []}

        async def _fetch(mid):
            return PDF, "application/octet-stream"

        async def _deliver(uid, msgs, reply_token=None):
            sent["msgs"].extend(msgs)

        async def _mark(ev):
            return None

        class _Sess:
            async def send_turn(self, text):
                sent["turns"].append(text)
                return "got it — your flight is BK123", []

        relay._fetch_content = _fetch
        relay._deliver = _deliver
        relay._mark_read = _mark
        relay._session = lambda *a, **k: _Sess()
        return relay, sent

    def test_file_event_archives_and_turns(self, tmp_path, monkeypatch):
        mod = self._patched_module(tmp_path, monkeypatch)
        relay, sent = self._relay(mod, tmp_path)
        ev = {"type": "message", "replyToken": "RT",
              "source": {"type": "user", "userId": "U1"},
              "message": {"id": "m1", "type": "file",
                          "fileName": "ticket.pdf", "fileSize": 777}}
        asyncio.run(relay.handle_event(ev))

        arch = tmp_path / "arch" / "U1" / "m1.pdf"
        assert arch.read_bytes() == PDF  # octet-stream -> .pdf via name
        day = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        journal = [json.loads(l) for l in
                   (tmp_path / "arch" / "U1"
                    / f"journal-{day}.jsonl").read_text().splitlines()]
        inn = [j for j in journal if j.get("kind") == "file"]
        assert inn and inn[0]["name"] == "ticket.pdf"
        assert inn[0]["mime"] == "application/pdf"
        assert inn[0]["size"] == 777
        assert inn[0]["url"].endswith("/relay-img/arch/U1/m1.pdf")
        assert any("[document received: ticket.pdf application/pdf" in t
                   and inn[0]["url"] in t for t in sent["turns"])
        assert "BK123" in sent["msgs"][0]["text"]

    def test_video_event_same_path(self, tmp_path, monkeypatch):
        mod = self._patched_module(tmp_path, monkeypatch)
        relay, sent = self._relay(mod, tmp_path)

        async def _fetch_mp4(mid):
            return b"\x00\x00\x00\x18ftypmp42", "video/mp4"
        ev = {"type": "message", "replyToken": "RT",
              "source": {"type": "user", "userId": "U1"},
              "message": {"id": "v9", "type": "video", "duration": 3000}}
        relay._fetch_content = _fetch_mp4
        asyncio.run(relay.handle_event(ev))
        assert (tmp_path / "arch" / "U1" / "v9.mp4").is_file()
        assert any("[video received:" in t for t in sent["turns"])

    def test_sticker_still_refused(self, tmp_path, monkeypatch):
        mod = self._patched_module(tmp_path, monkeypatch)
        relay, sent = self._relay(mod, tmp_path)
        ev = {"type": "message", "replyToken": "RT",
              "source": {"type": "user", "userId": "U1"},
              "message": {"id": "s1", "type": "sticker",
                          "stickerId": "1"}}
        asyncio.run(relay.handle_event(ev))
        assert "sticker" in sent["msgs"][0]["text"]
        assert not sent["turns"]
        assert not (tmp_path / "arch" / "U1").exists()
