"""Unit tests for the persona-photo-store drop staged under
integrations/ada-voice/ (card persona-photo-store, 2026-11-24).

Personas couldn't hold or reshow photos: bank docs were text-only and
no tool returned a stored image URL to the relay's _image_msgs path —
kaewta couldn't re-show kk's car photo on request. The drop adds:

- backend/tools.d/asset_save.py — stores an inbound LINE image (or any
  fetchable image URL) under <LINE_MEDIA_ARCHIVE_DIR>/persona-assets/
  (publicly served at /relay-img/arch/persona-assets/) and upserts an
  assets/<slug> bank doc carrying meta.image_url, riding the
  ada_remember ACL + staged-writes lane (pending route 'asset').
- backend/memory_ops.py — _doc_to_hit surfaces meta.image_url on hits;
  new asset_remember() upsert helper.
- backend/memory_pending.py + scripts/ada/memory-pending.py — the
  'asset' pending route so staged saves approve through the real write.
- backend/tool_runner/memory.py — ada_memory_search promotes the first
  image-bearing hit to a top-level image_url; the relay's _images_from
  turns it into a real image message (draft/archival hits never
  auto-attach).
- backend/tool_guide.yml + ssot.tool-surface.yml + tools.d manifest
  snippet — tool-surface registration (coverage_debt until a live
  scenario lands).

Strategy mirrors test_cpt_post_drop.py / test_draft_hit_frame.py:
asset_save loads standalone under stubbed backend.* seams; the patched
tool_runner/memory.py imports under a stub backend.tool_runner.common;
memory_ops functions are ast-extracted and exec'd; patches gate
through tests/ada/_drops.py against the live checkout (ADA_PI env or
~/CascadeProjects/ada-voice).
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import types as pytypes
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from tests.ada._checkout import materialize_head
from tests.ada._drops import apply_patch, check_patch, drop_guard_ok

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
TOOL = DROP / "backend" / "tools.d" / "asset_save.py"
MANIFEST_SNIPPET = DROP / "backend" / "tools.d" / "manifest.asset_save.yml"
ADA_PI = Path(os.environ.get("ADA_PI",
                             str(Path.home() / "CascadeProjects" / "ada-voice")))

PATCHES = {
    "backend/memory_ops.py":
        DROP / "backend" / "memory_ops.persona-photo-store.patch",
    "backend/memory_pending.py":
        DROP / "backend" / "memory_pending.persona-photo-store.patch",
    "backend/tool_runner/memory.py":
        DROP / "backend" / "tool_runner.memory.persona-photo-store.patch",
    "backend/tool_guide.yml":
        DROP / "backend" / "tool_guide.persona-photo-store.patch",
    "scripts/ada/memory-pending.py":
        DROP / "scripts" / "ada.memory-pending.persona-photo-store.patch",
    "docs/ssot/ssot.tool-surface.yml":
        DROP / "ssot.tool-surface.persona-photo-store.patch",
}

JPEG = (b"\xff\xd8\xff\xe0" + b"JFIF\x00" + b"\x00" * 64
        + b"\xff\xd9")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _ada_pi_file(rel: str) -> Path:
    p = ADA_PI / rel
    if not p.exists():
        pytest.skip(f"no ada-voice checkout at {ADA_PI} — drop ships the "
                    f"patches, not the files")
    return p


@pytest.fixture()
def patched_tree(tmp_path):
    """Apply all drop patches to copies of the ada-voice sources —
    patches that already merged upstream (or diverged post-merge) test
    the live file instead; see tests/ada/_drops.py."""
    for rel, patch in PATCHES.items():
        src = _ada_pi_file(rel)
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        apply_patch(patch, tmp_path)
    return tmp_path


# ------------------------------------------------------------- patch gate

def test_patches_apply_and_compile(patched_tree):
    """Every staged patch resolves against the live ada-voice tree
    (applied, or already merged) and the result must compile/parse."""
    for rel in PATCHES:
        p = patched_tree / rel
        if rel.endswith(".py"):
            compile(p.read_text(), str(p), "exec")
        elif rel.endswith(".yml"):
            yaml.safe_load(p.read_text())


@pytest.mark.skipif(not (ADA_PI / ".git").exists(),
                    reason="no ada-voice checkout reachable")
def test_patch_states_healthy(tmp_path):
    """Base-commit guard: every patch must apply OR already be merged
    upstream; divergence only fails when nothing in the drop landed
    (pending drop on a rotted base — tests/ada/_drops.py)."""
    dst = tmp_path / "ada-voice"
    materialize_head(dst, ADA_PI)
    states = {rel: check_patch(patch, dst)
              for rel, patch in PATCHES.items()}
    assert drop_guard_ok(states.values()), (
        f"drop rotted on its base — re-dispatch: {states}")
    # the new tool file itself must compile — merged upstream = already
    # in the clone; still pending = copy the staged file in.
    tgt = dst / "backend" / "tools.d" / "asset_save.py"
    if not tgt.exists():
        subprocess.run(["cp", str(TOOL), str(tgt)], check=True)
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(tgt)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]


# ------------------------------------------------------- asset_save tool

def _load_tool(monkeypatch, tmp_path):
    """Import asset_save standalone: stub the backend.* seams its run()
    reaches for — memory_ops (bank resolution + the asset upsert),
    memory_banks._slug, tool_runner.common.session_chat_id."""
    monkeypatch.setenv("LINE_MEDIA_ARCHIVE_DIR", str(tmp_path / "arch"))
    monkeypatch.setenv("LINE_PUBLIC_IMG_BASE",
                       "https://relay.test/relay-img")
    monkeypatch.setenv("ADA_RELAY_PUBLIC_BASE", "")
    (tmp_path / "arch").mkdir(exist_ok=True)

    calls = {"asset_remember": [], "staged": [], "acls": []}

    async def _asset_remember(mddb, registry, instance, bank, key, text,
                              image_url, subject=None, session_id=None,
                              person_entity=None):
        calls["asset_remember"].append(
            {"bank": bank, "key": key, "text": text,
             "image_url": image_url, "subject": subject,
             "person_entity": person_entity})
        return {"verb": "create", "bank": bank, "key": key}

    ops = pytypes.ModuleType("backend.memory_ops")
    ops.persona_bank_for = lambda banks, ident: SimpleNamespace(
        name="personal-kk")
    ops.asset_remember = _asset_remember

    banks_mod = pytypes.ModuleType("backend.memory_banks")
    banks_mod._slug = lambda text, max_words=6: "-".join(
        re.sub(r"[^a-z0-9]+", "-", str(text or "").lower())
        .strip("-").split("-")[:max_words]) or "note"

    common = pytypes.ModuleType("backend.tool_runner.common")
    common.session_chat_id = lambda runner, channel: ""

    backend = pytypes.ModuleType("backend")
    backend.__path__ = []
    backend.memory_ops = ops
    tr = pytypes.ModuleType("backend.tool_runner")
    tr.__path__ = []
    tr.common = common

    monkeypatch.setitem(sys.modules, "backend", backend)
    monkeypatch.setitem(sys.modules, "backend.memory_ops", ops)
    monkeypatch.setitem(sys.modules, "backend.memory_banks", banks_mod)
    monkeypatch.setitem(sys.modules, "backend.tool_runner", tr)
    monkeypatch.setitem(sys.modules, "backend.tool_runner.common", common)

    spec = importlib.util.spec_from_file_location(
        f"tools_d.asset_save_chaba_{id(tmp_path)}", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, calls


def _runner(**over):
    """Fake ToolRunner carrying just the seams asset_save touches."""
    bank_cfg = SimpleNamespace(name="personal-kk", write_policy="direct")
    banks = SimpleNamespace(
        bank=lambda name: bank_cfg,
        personal_bank_name=lambda entity: "personal-kk",
    )
    r = SimpleNamespace(
        mddb=object(),
        banks=banks,
        memory=SimpleNamespace(instance="test"),
        session_id="sess-1",
        _memory_identity=lambda: "person.kk",
        _check_memory_write_allowed=lambda *a, **k: None,
        _scan_memory_write=lambda **k: None,
        _memory_staging_required=lambda route: False,
        _stage_memory_write=None,
    )
    for k, v in over.items():
        setattr(r, k, v)
    return r


def _arch(tmp_path, chat="C123", name="mid1.jpg", data=JPEG):
    d = tmp_path / "arch" / chat
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_bytes(data)
    return f


def _sniff_cases(mod):
    assert mod._sniff_image(JPEG) == ("image/jpeg", ".jpg")
    assert mod._sniff_image(PNG) == ("image/png", ".png")
    assert mod._sniff_image(b"GIF89a" + b"\x00" * 8) == \
        ("image/gif", ".gif")
    assert mod._sniff_image(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 8) == \
        ("image/webp", ".webp")
    assert mod._sniff_image(b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8) \
        is None
    assert mod._sniff_image(b"not an image at all") is None


def test_sniff_and_resolve(monkeypatch, tmp_path):
    mod, _ = _load_tool(monkeypatch, tmp_path)
    _sniff_cases(mod)
    f = _arch(tmp_path, name="photo.jpg")
    # /relay-img/arch/ URL and absolute archive path both resolve.
    p, err = mod._resolve_archive("/relay-img/arch/C123/photo.jpg")
    assert err is None and p == f.resolve()
    p, err = mod._resolve_archive(str(f))
    assert err is None and p == f.resolve()
    p, err = mod._resolve_archive(
        "https://relay.test/relay-img/arch/C123/photo.jpg")
    assert err is None and p == f.resolve()
    # Traversal + outside-archive reads refuse.
    for bad in ("/relay-img/arch/../secret.jpg",
                "/relay-img/arch/../../etc/passwd",
                "/etc/passwd",
                str(tmp_path / "outside.jpg")):
        p, err = mod._resolve_archive(bad)
        assert p is None and err, bad
    # Non-arch http URLs are NOT local reads — run() fetches them.
    p, err = mod._resolve_archive("https://x.test/pic.png")
    assert p is None and "fetchable" in err


def test_latest_chat_image(monkeypatch, tmp_path):
    mod, _ = _load_tool(monkeypatch, tmp_path)
    f = _arch(tmp_path, chat="C999", name="m1.jpg")
    mf = tmp_path / "arch" / "manifest.jsonl"
    entries = [
        {"chat_id": "C999", "kind": "file", "message_id": "f1",
         "path": str(tmp_path / "arch" / "C999" / "f1.pdf")},
        {"chat_id": "C999", "kind": "image", "message_id": "m1",
         "mime": "image/jpeg", "path": str(f), "sender": "KK",
         "ts": "2026-11-24T10:00:00"},
        {"chat_id": "OTHER", "kind": "image", "message_id": "m2",
         "mime": "image/jpeg", "path": "/nonexistent/x.jpg"},
    ]
    mf.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    p, e = mod._latest_chat_image("C999")
    assert p == f.resolve() and e["message_id"] == "m1"
    p, e = mod._latest_chat_image("C555")
    assert p is None and e is None


def _run(mod, runner, **kw):
    return asyncio.run(mod.run(runner, **kw))


def test_run_saves_asset(monkeypatch, tmp_path):
    mod, calls = _load_tool(monkeypatch, tmp_path)
    f = _arch(tmp_path, name="kk-crv.jpg")
    res = _run(mod, _runner(), name="kk-crv",
               description="KK's CR-V in the driveway",
               media_url="/relay-img/arch/C123/kk-crv.jpg")
    assert res["ok"], res
    assert res["verb"] == "create" and res["key"] == "assets/kk-crv"
    expected = ("https://relay.test/relay-img/arch/persona-assets/"
                "kk-crv.jpg")
    assert res["image_url"] == expected
    saved = tmp_path / "arch" / "persona-assets" / "kk-crv.jpg"
    assert saved.read_bytes() == JPEG
    assert len(calls["asset_remember"]) == 1
    call = calls["asset_remember"][0]
    assert call["bank"] == "personal-kk"
    assert call["key"] == "assets/kk-crv"
    assert call["image_url"] == expected
    assert call["person_entity"] == "person.kk"
    assert "image_url: " + expected in call["text"]


def test_run_dedupe_and_revise(monkeypatch, tmp_path):
    mod, calls = _load_tool(monkeypatch, tmp_path)
    _arch(tmp_path, name="a.jpg")
    r1 = _run(mod, _runner(), name="kk-crv",
              media_url="/relay-img/arch/C123/a.jpg")
    assert r1["ok"] and r1["file"] == "kk-crv.jpg"
    # Same bytes again -> same filename (idempotent re-save).
    r2 = _run(mod, _runner(), name="kk-crv",
              media_url="/relay-img/arch/C123/a.jpg")
    assert r2["ok"] and r2["file"] == "kk-crv.jpg"
    # Different bytes under the same slug+ext -> hash-suffixed file;
    # the doc key stays assets/kk-crv (correct-in-place on write).
    _arch(tmp_path, name="b.jpg", data=JPEG + b"different-bytes")
    r3 = _run(mod, _runner(), name="kk-crv",
              media_url="/relay-img/arch/C123/b.jpg")
    assert r3["ok"] and r3["file"].startswith("kk-crv-") \
        and r3["file"].endswith(".jpg")
    assert calls["asset_remember"][-1]["key"] == "assets/kk-crv"


def test_run_latest_image_fallback(monkeypatch, tmp_path):
    mod, calls = _load_tool(monkeypatch, tmp_path)
    f = _arch(tmp_path, chat="C777", name="m9.jpg")
    (tmp_path / "arch" / "manifest.jsonl").write_text(json.dumps({
        "chat_id": "C777", "kind": "image", "message_id": "m9",
        "mime": "image/jpeg", "path": str(f), "sender": "KK",
        "ts": "2026-11-24T11:00:00"}) + "\n")

    def _chat(runner, channel):
        return "C777" if channel == "line" else ""

    # session_chat_id is stubbed at module load — patch the module attr.
    import backend.tool_runner.common as _c
    _c.session_chat_id = _chat
    res = _run(mod, _runner(), name="kk-crv",
               description="car photo")
    assert res["ok"], res
    assert res["key"] == "assets/kk-crv"
    assert "KK" in calls["asset_remember"][0]["text"]


def test_run_no_source_and_non_image(monkeypatch, tmp_path):
    mod, _ = _load_tool(monkeypatch, tmp_path)
    res = _run(mod, _runner(), name="x")
    assert res["ok"] is False and "no inbound image" in res["error"]
    _arch(tmp_path, name="doc.jpg", data=b"plain text bytes")
    res = _run(mod, _runner(), name="x",
               media_url="/relay-img/arch/C123/doc.jpg")
    assert res["ok"] is False and "not a supported image" in res["error"]


def test_run_confirmed_bank_refuses(monkeypatch, tmp_path):
    mod, calls = _load_tool(monkeypatch, tmp_path)
    _arch(tmp_path)
    runner = _runner()
    runner.banks.bank = lambda name: SimpleNamespace(
        name="general", write_policy="confirmed")
    res = _run(mod, runner, name="x", bank="general",
               media_url="/relay-img/arch/C123/mid1.jpg")
    assert res["ok"] is False and "confirmed" in res["error"]
    assert not calls["asset_remember"]


def test_run_acl_denied_surfaces(monkeypatch, tmp_path):
    mod, _ = _load_tool(monkeypatch, tmp_path)
    _arch(tmp_path)

    def _deny(*a, **k):
        raise PermissionError("memory bank 'x' is not available")

    runner = _runner()
    runner._check_memory_write_allowed = _deny
    res = _run(mod, runner, name="x",
               media_url="/relay-img/arch/C123/mid1.jpg")
    assert res["ok"] is False and "not available" in res["error"]


def test_run_staged_for_non_admin(monkeypatch, tmp_path):
    mod, calls = _load_tool(monkeypatch, tmp_path)
    _arch(tmp_path)
    staged = []

    async def _stage(**kw):
        staged.append(kw)
        return {"ok": True, "staged": True, "id": "mp-test1",
                "note": "held for review"}

    runner = _runner()
    runner._memory_staging_required = lambda route: True
    runner._stage_memory_write = _stage
    res = _run(mod, runner, name="kk-crv",
               media_url="/relay-img/arch/C123/mid1.jpg")
    assert res["ok"] and res["staged"] and res["id"] == "mp-test1"
    # The file still landed (it's already public via /relay-img/arch/)
    # but NO bank doc was written — approval replays route 'asset'.
    assert not calls["asset_remember"]
    assert staged[0]["route"] == "asset"
    assert staged[0]["args"]["image_url"].endswith(
        "/arch/persona-assets/kk-crv.jpg")
    assert staged[0]["key"] == "assets/kk-crv"


def test_manifest_fragment_matches_declaration(monkeypatch, tmp_path):
    """manifest snippet key/module == DECLARATION name (tools_loader
    validates manifest key against the module's declared name)."""
    mod, _ = _load_tool(monkeypatch, tmp_path)
    frag = yaml.safe_load(MANIFEST_SNIPPET.read_text())
    cfg = frag["tools"]["asset_save"]
    assert cfg["module"] == "asset_save"
    assert mod.DECLARATION["name"] == "asset_save"
    assert mod.DECLARATION["parameters"]["additionalProperties"] is False


# --------------------------------------------------------- memory_ops

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


def _meta_first(meta, key, default=None):
    v = (meta or {}).get(key)
    if isinstance(v, list):
        return v[0] if v else default
    return v if v is not None else default


def _doc_to_hit_globals():
    return {
        "doc_effective_status":
            lambda doc: _meta_first(doc.get("meta") or {}, "status",
                                    "active"),
        "_meta_first": _meta_first,
        "_draft_visible": lambda bank, doc, instance: False,
        "ADA_HIT_MAX_CHARS": 2000,
        "ADA_BANK_CONFIDENCE_MIN": 0.4,
        "Any": Any,
    }


def test_doc_to_hit_surfaces_image_url(patched_tree):
    """_doc_to_hit: meta.image_url lands on the hit so recall can
    re-show the picture; absent meta yields None (never a bogus key)."""
    src = patched_tree / "backend/memory_ops.py"
    f = _extract_func(src, "_doc_to_hit", _doc_to_hit_globals())
    bank = SimpleNamespace(status_outcome=False, name="personal-kk")
    doc = {"key": "assets/kk-crv", "contentMd": "KK's CR-V",
           "meta": {"status": ["active"], "kind": ["note"],
                    "image_url": ["https://x/arch/persona-assets/a.jpg"]}}
    hit = f(bank, doc, "test", False)
    assert hit["image_url"] == "https://x/arch/persona-assets/a.jpg"
    doc2 = {"key": "fact/x", "contentMd": "plain",
            "meta": {"status": ["active"]}}
    hit2 = f(bank, doc2, "test", False)
    assert hit2["image_url"] is None


def _asset_remember_globals():
    async def _noop(*a, **k):
        return None

    return {
        "datetime": datetime,
        "timezone": timezone,
        "memory_meta": lambda *a, **k: {"kind": ["note"],
                                        "status": ["active"]},
        "memory_write_guard": SimpleNamespace(
            check_write=lambda **kw: None,
            warn_if_bank_large=_noop),
        "_warn_unknown_meta": lambda *a, **k: None,
        "_must": lambda res, what: None,
        "_queued_note": lambda out, res: out,
        "Any": Any,
    }


def _fake_registry(allowed=True):
    bank = SimpleNamespace(name="personal-kk", scope="person",
                           kinds=["note"], mddb_collection="coll-kk",
                           env=None)
    return SimpleNamespace(
        personal_bank_name=lambda e: "personal-kk",
        bank=lambda name: bank,
        acl_decision=lambda *a, **k: {"allowed": allowed}), bank


def _fake_mddb(existing=None):
    calls = {"add": [], "update": []}

    async def _add(collection, key, lang, text, meta, **kw):
        calls["add"].append({"collection": collection, "key": key,
                             "text": text, "meta": meta})
        return {"ok": True}

    async def _update(collection, key, **kw):
        calls["update"].append({"collection": collection, "key": key,
                                **kw})
        return {"ok": True}

    async def _get(collection, key):
        return existing

    return SimpleNamespace(get_document=_get, add_document=_add,
                           update_document=_update), calls


def test_asset_remember_create_and_correct(patched_tree):
    """asset_remember upserts assets/<slug> with meta.image_url +
    written_by=['asset_save']; an existing doc corrects in place."""
    src = patched_tree / "backend/memory_ops.py"
    fn = _extract_func(src, "asset_remember",
                       _asset_remember_globals())
    registry, bank = _fake_registry()
    mddb, calls = _fake_mddb()
    res = asyncio.run(fn(
        mddb, registry, "test", "personal-kk", "assets/kk-crv",
        "KK's CR-V\n\nimage_url: https://x/a.jpg",
        "https://x/a.jpg", subject="kk-crv", session_id="s1",
        person_entity="person.kk"))
    assert res["verb"] == "create" and res["key"] == "assets/kk-crv"
    meta = calls["add"][0]["meta"]
    assert meta["image_url"] == ["https://x/a.jpg"]
    assert meta["written_by"] == ["asset_save"]
    # Second save of the same slug -> correct via update_document.
    mddb2, calls2 = _fake_mddb(existing={"key": "assets/kk-crv"})
    res2 = asyncio.run(fn(
        mddb2, registry, "test", "personal-kk", "assets/kk-crv",
        "new body", "https://x/b.jpg", person_entity="person.kk"))
    assert res2["verb"] == "correct"
    assert calls2["update"][0]["meta"]["image_url"] == ["https://x/b.jpg"]


def test_asset_remember_acl_denied(patched_tree):
    src = patched_tree / "backend/memory_ops.py"
    fn = _extract_func(src, "asset_remember",
                       _asset_remember_globals())
    registry, _ = _fake_registry(allowed=False)
    mddb, calls = _fake_mddb()
    with pytest.raises(PermissionError):
        asyncio.run(fn(mddb, registry, "test", "personal-kk",
                       "assets/x", "body", "https://x/a.jpg",
                       person_entity="person.kk"))
    assert not calls["add"] and not calls["update"]


# ------------------------------------------- tool_runner/memory promote

def _load_patched_memory(patched_tree, tmp_path, monkeypatch):
    """Import the patched backend/tool_runner/memory.py under a stub
    backend.tool_runner.common — same trick as test_draft_hit_frame."""
    pkg = tmp_path / "backend"
    trun = pkg / "backend" / "tool_runner"
    trun.mkdir(parents=True)
    (trun / "__init__.py").write_text("")
    (trun / "common.py").write_text(textwrap.dedent("""\
        import asyncio, json, logging, os, re, sys, time
        import httpx
        from datetime import datetime, timedelta, timezone
        from pathlib import Path
        from types import SimpleNamespace
        from typing import Any
        logger = logging.getLogger("t")
        memory_ops = SimpleNamespace(
            memory_search=None,          # per-test coroutine
            is_transcript_shaped=lambda content, **k:
                "=== MESSAGE" in str(content or ""),
            _keyword_rank=lambda docs, q: docs,
        )
        def _first(v, default=None):
            if isinstance(v, list):
                return v[0] if v else default
            return v if v is not None else default
        """))
    shutil.copy(patched_tree / "backend/tool_runner/memory.py",
                trun / "memory.py")
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


def _hit(key, image_url=None, **kw):
    h = {"key": key, "score": 0.8, "status": "active",
         "bank": "personal-kk", "content": f"body for {key}"}
    if image_url is not None:
        h["image_url"] = image_url
    h.update(kw)
    return h


def test_search_promotes_first_image_hit(patched_tree, tmp_path,
                                         monkeypatch):
    """The first usable image-bearing hit promotes its image_url to a
    TOP-LEVEL scalar — _safe_args keeps scalars so the relay's
    _images_from attaches it to the reply."""
    mod = _load_patched_memory(patched_tree, tmp_path, monkeypatch)
    runner = _fake_runner(mod, [
        _hit("fact/plain", score=0.9),
        _hit("assets/kk-crv", "https://x/arch/persona-assets/a.jpg",
             score=0.8),
        _hit("assets/other", "https://x/arch/persona-assets/b.jpg",
             score=0.7),
    ])
    out = asyncio.run(mod.MemoryMixin.ada_memory_search(
        runner, query="kk car photo", bank="personal-kk"))
    assert out["image_url"] == "https://x/arch/persona-assets/a.jpg"
    assert "image_note" in out
    # per-hit image_url survives for explicit chat_send resends
    assert out["hits"][1]["image_url"].endswith("a.jpg")


def test_search_skips_draft_and_archival_images(patched_tree, tmp_path,
                                                monkeypatch):
    """Unverified content never auto-attaches: a draft hit's image_url
    stays per-hit only; the promotion walks to the next usable hit.
    Transcript-shaped (archival) hits are skipped the same way."""
    mod = _load_patched_memory(patched_tree, tmp_path, monkeypatch)
    runner = _fake_runner(mod, [
        _hit("gap/x", "https://x/draft.jpg", score=0.95,
             draft=True, unverified=True),
        _hit("dump/session", "https://x/archival.jpg", score=0.9,
             content="=== MESSAGE 1 - System ===\nraw transcript"),
        _hit("assets/kk-crv", "https://x/arch/persona-assets/a.jpg",
             score=0.8),
    ])
    out = asyncio.run(mod.MemoryMixin.ada_memory_search(
        runner, query="q", bank="personal-kk"))
    assert out["image_url"] == "https://x/arch/persona-assets/a.jpg"
    # and when ONLY unverified hits carry an image, nothing promotes
    runner2 = _fake_runner(mod, [
        _hit("gap/x", "https://x/draft.jpg", score=0.95,
             draft=True, unverified=True),
        _hit("dump/session", "https://x/archival.jpg", score=0.9,
             content="=== MESSAGE 1 - System ===\nraw transcript"),
    ])
    out2 = asyncio.run(mod.MemoryMixin.ada_memory_search(
        runner2, query="q", bank="personal-kk"))
    assert "image_url" not in out2


def test_search_no_image_no_key(patched_tree, tmp_path, monkeypatch):
    mod = _load_patched_memory(patched_tree, tmp_path, monkeypatch)
    runner = _fake_runner(mod, [
        _hit("fact/plain"),
        _hit("assets/bad-scheme", "notaurl", score=0.7),
        _hit("assets/rel", "/v1/drive/media/x", score=0.6),
    ])
    out = asyncio.run(mod.MemoryMixin.ada_memory_search(
        runner, query="q", bank="personal-kk"))
    # '/v1/' host-relative media links DO promote (relay resolves them
    # against the lane backend) — 'notaurl' does not.
    assert out["image_url"] == "/v1/drive/media/x"
    runner2 = _fake_runner(mod, [_hit("fact/plain"),
                                 _hit("assets/bad", "notaurl")])
    out2 = asyncio.run(mod.MemoryMixin.ada_memory_search(
        runner2, query="q", bank="personal-kk"))
    assert "image_url" not in out2
