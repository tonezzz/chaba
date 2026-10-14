"""Unit tests for the draft-hit-frame drop staged under
integrations/ada-voice/ (card ada-memory-search-draft-gap-notes-mislea-406683,
ADA-0607, 2026-10-13).

The card: status=draft memory docs — auto-extracted candidates and
recall-miss "knowledge gap" notes — surface in ada_memory_search flagged
only by JSON fields (draft=true / unverified=true). The live model read
them as facts anyway. The drop fixes four leaks:

- backend/tool_runner/memory.py — draft hits get their content wrapped
  in an in-band UNVERIFIED DRAFT frame (same pattern as ARCHIVAL_HIT_FRAME).
- backend/memory_ops.py — include_inactive audit reads flag drafts too
  (previously they returned status=draft with no draft/unverified flag,
  so the tool boundary could not frame them).
- backend/realtime_provider.py — draft/unverified hits no longer count
  as the "confident hit" for the recall gate, and the dead-turn
  fallback/digest never speaks them as the answer.
- backend/tool_guide.yml — the ada_memory_search guide entry documents
  the frame.

Strategy: apply the staged patches to copies of the live ada-voice sources
(ADA_PI env or ~/CascadeProjects/ada-voice — skipped when absent), compile
them, then exercise the behavior. backend modules carry heavy deps
(google.genai etc.) so functions are exercised two ways: the patched
tool_runner/memory.py is imported under a stub `backend.tool_runner.common`,
and the memory_ops / realtime_provider methods are ast-extracted from the
patched source and exec'd with stub globals — the assertions run the
patched code itself, not a copy.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import logging
import os
import subprocess
import sys
import textwrap
import time
import types as pytypes
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
ADA_PI = Path(os.environ.get("ADA_PI",
                             str(Path.home() / "CascadeProjects/ada-voice")))

PATCHES = {
    "backend/tool_runner/memory.py":
        DROP / "backend" / "tool_runner.memory.draft-hit-frame.patch",
    "backend/memory_ops.py":
        DROP / "backend" / "memory_ops.draft-include-inactive.patch",
    "backend/realtime_provider.py":
        DROP / "backend" / "realtime_provider.draft-hit-gates.patch",
    "backend/tool_guide.yml":
        DROP / "backend" / "tool_guide.draft-hit-frame.patch",
}


def _ada_pi_file(rel: str) -> Path:
    p = ADA_PI / rel
    if not p.exists():
        pytest.skip(f"no ada-voice checkout at {ADA_PI} — drop ships the "
                    f"patches, not the files")
    return p


@pytest.fixture()
def patched_tree(tmp_path):
    """Apply all drop patches to copies of the ada-voice sources."""
    for rel, patch in PATCHES.items():
        src = _ada_pi_file(rel)
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        subprocess.run(["git", "apply", str(patch)], cwd=tmp_path,
                       check=True, capture_output=True)
    return tmp_path


# ------------------------------------------------------------- patch gate


def test_patches_apply_and_compile(patched_tree):
    """Every staged patch must apply to the live ada-voice tree and the
    result must compile/parse — the drop is only as good as its apply."""
    for rel in PATCHES:
        p = patched_tree / rel
        if rel.endswith(".py"):
            compile(p.read_text(), str(p), "exec")
        elif rel.endswith(".yml"):
            yaml.safe_load(p.read_text())


def test_guide_documents_frame(patched_tree):
    text = (patched_tree / "backend/tool_guide.yml").read_text()
    assert "UNVERIFIED" in text and "DRAFT" in text


# ------------------------------------------------- tool_runner/memory.py


def _load_patched_memory(patched_tree, tmp_path, monkeypatch):
    """Import the patched backend/tool_runner/memory.py under a stub
    backend.tool_runner.common — only the names the module touches on
    the banks-search path need to exist."""
    pkg = tmp_path / "backend"
    trun = pkg / "backend" / "tool_runner"
    trun.mkdir(parents=True)
    (trun / "__init__.py").write_text("")
    (trun / "common.py").write_text(textwrap.dedent("""\
        import asyncio, json, logging, os, re, sys, time
        from datetime import datetime, timedelta, timezone
        from pathlib import Path
        from types import SimpleNamespace
        from typing import Any
        logger = logging.getLogger("t")
        memory_ops = SimpleNamespace(
            memory_search=None,          # per-test coroutine
            is_transcript_shaped=lambda *a, **k: False,
            _keyword_rank=lambda docs, q: docs,
        )
        def _first(v, default=None):
            if isinstance(v, list):
                return v[0] if v else default
            return v if v is not None else default
        """))
    shutil_src = patched_tree / "backend/tool_runner/memory.py"
    (trun / "memory.py").write_bytes(shutil_src.read_bytes())
    monkeypatch.syspath_prepend(str(pkg))
    for m in list(sys.modules):
        if m == "backend" or m.startswith("backend."):
            del sys.modules[m]
    import backend.tool_runner.memory as mod
    return mod


def _fake_runner(mod, hits):
    async def _search(mddb, banks, bank, query, limit,
                      include_inactive, person_entity=None):
        return {"hits": list(hits), "degraded": False}
    mod.memory_ops.memory_search = _search
    fake = SimpleNamespace(
        mddb=SimpleNamespace(),
        banks=SimpleNamespace(),
        chaba=None,
        session_id="t",
        _memory_identity=lambda: None,
        _require_chaba=lambda: None,
    )
    return fake


def test_draft_hit_content_framed(patched_tree, tmp_path, monkeypatch):
    mod = _load_patched_memory(patched_tree, tmp_path, monkeypatch)
    draft = {"key": "gap/2026-10-13-wifi", "score": 0.7, "status": "draft",
             "draft": True, "unverified": True, "bank": "personal",
             "content": "# Knowledge gap\nAda could not answer: wifi?"}
    active = {"key": "fact/coffee", "score": 0.8, "status": "active",
              "bank": "general", "content": "Tony takes coffee black."}
    runner = _fake_runner(mod, [draft, active])
    out = asyncio.run(mod.MemoryMixin.ada_memory_search(
        runner, query="wifi password", bank="general"))
    by_key = {h["key"]: h for h in out["hits"]}
    d = by_key["gap/2026-10-13-wifi"]
    assert d["draft"] is True and d["unverified"] is True
    assert d["content"].startswith("[UNVERIFIED DRAFT")
    assert "NOT a confirmed fact" in d["content"]
    assert "# Knowledge gap" in d["content"]
    a = by_key["fact/coffee"]
    assert a["content"] == "Tony takes coffee black."
    assert "draft" not in a


def test_unverified_active_hit_unframed(patched_tree, tmp_path, monkeypatch):
    """Low-confidence ACTIVE docs keep the JSON flag only — framing is
    scoped to drafts per the card."""
    mod = _load_patched_memory(patched_tree, tmp_path, monkeypatch)
    hits = [{"key": "fact/old", "score": 0.7, "status": "active",
             "unverified": True, "confidence": 0.3, "bank": "general",
             "content": "something half-remembered"}]
    runner = _fake_runner(mod, hits)
    out = asyncio.run(mod.MemoryMixin.ada_memory_search(
        runner, query="q", bank="general"))
    h = out["hits"][0]
    assert h["unverified"] is True
    assert not h["content"].startswith("[UNVERIFIED DRAFT")


# ---------------------------------------------------------- memory_ops


def _extract_func(path: Path, func: str, globals_extra: dict):
    """exec one top-level function from a source file with stub globals."""
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == func)
    src = textwrap.dedent(ast.get_source_segment(path.read_text(), node))
    ns = dict(globals_extra)
    exec(compile(src, str(path), "exec"), ns)
    return ns[func]


def test_include_inactive_flags_draft(patched_tree):
    """_doc_to_hit: an include_inactive audit read must still flag a
    status=draft doc (draft=True, unverified=True) so the tool boundary
    can frame it — the pre-patch shape returned neither."""
    src = patched_tree / "backend/memory_ops.py"

    def _meta_first(meta, key, default=None):
        v = (meta or {}).get(key)
        if isinstance(v, list):
            return v[0] if v else default
        return v if v is not None else default

    g = {
        "doc_effective_status":
            lambda doc: _meta_first(doc.get("meta") or {}, "status",
                                    "active"),
        "_meta_first": _meta_first,
        "_draft_visible": lambda bank, doc, instance: False,
        "ADA_HIT_MAX_CHARS": 2000,
        "ADA_BANK_CONFIDENCE_MIN": 0.4,
        "Any": Any,
    }
    f = _extract_func(src, "_doc_to_hit", g)
    bank = SimpleNamespace(status_outcome=False, name="personal")
    doc = {"key": "gap/x", "contentMd": "draft body",
           "meta": {"status": ["draft"], "scope": ["tony"]}}
    hit = f(bank, doc, "tony", True)
    assert hit is not None and hit["status"] == "draft"
    assert hit["draft"] is True and hit["unverified"] is True


# ----------------------------------------------------- realtime_provider


def _extract_method(path: Path, cls: str, meth: str,
                    globals_extra: dict):
    tree = ast.parse(path.read_text())
    node = next(
        m for c in tree.body if isinstance(c, ast.ClassDef)
        and c.name == cls
        for m in c.body
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        and m.name == meth)
    src = textwrap.dedent(
        ast.get_source_segment(path.read_text(), node))
    ns = dict(globals_extra)
    exec(compile(src, str(path), "exec"), ns)
    return ns[meth]


def _speakable(text, limit=160):
    for line in str(text or "").splitlines():
        line = line.strip().lstrip("#*>-• ").strip()
        if line:
            return line[:limit].rstrip()
    return ""


def test_confident_gate_ignores_drafts(patched_tree):
    src = patched_tree / "backend/realtime_provider.py"
    f = _extract_method(src, "GeminiLiveProvider", "_note_search_result",
                        {"time": time, "Any": Any})
    prov = SimpleNamespace(_recall_gate_score=0.6,
                           _strong_hit_at=float("-inf"))
    # A draft at 0.9 must NOT register as the confident hit.
    f(prov, {"hits": [{"score": 0.9, "draft": True,
                       "unverified": True}]})
    assert prov._strong_hit_at == float("-inf")
    f(prov, {"hits": [{"score": 0.9, "unverified": True}]})
    assert prov._strong_hit_at == float("-inf")
    f(prov, {"hits": [{"score": 0.9}]})
    assert prov._strong_hit_at != float("-inf")


def test_dead_turn_fallback_skips_drafts(patched_tree):
    src = patched_tree / "backend/realtime_provider.py"
    f = _extract_method(src, "GeminiLiveProvider", "_dead_turn_fallback",
                        {"_first_speakable_line": _speakable, "Any": Any})
    prov = SimpleNamespace()
    res = [("ada_memory_search", {"hits": [
        {"score": 0.9, "draft": True, "content": "unreviewed guess"},
    ]})]
    out = f(prov, res)
    assert "unreviewed guess" not in out
    res = [("ada_memory_search", {"hits": [
        {"score": 0.9, "draft": True, "content": "unreviewed guess"},
        {"score": 0.5, "content": "verified answer"},
    ]})]
    out = f(prov, res)
    assert "verified answer" in out


def test_dead_turn_digest_skips_drafts(patched_tree):
    src = patched_tree / "backend/realtime_provider.py"
    f = _extract_method(src, "GeminiLiveProvider", "_dead_turn_digest",
                        {"_first_speakable_line": _speakable, "Any": Any})
    prov = SimpleNamespace()
    res = [("ada_memory_search", {"hits": [
        {"score": 0.9, "draft": True, "key": "gap/x",
         "content": "unreviewed guess"},
    ]})]
    out = f(prov, res)
    assert "unreviewed guess" not in out
    assert "draft" in out.lower()
    res = [("ada_memory_search", {"hits": [
        {"score": 0.9, "draft": True, "key": "gap/x",
         "content": "unreviewed guess"},
        {"score": 0.5, "key": "fact/y", "content": "verified answer"},
    ]})]
    out = f(prov, res)
    assert "verified answer" in out and "unreviewed guess" not in out
