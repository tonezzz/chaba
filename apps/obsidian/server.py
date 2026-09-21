#!/usr/bin/env python3
"""apps/obsidian — mini web vault for Ada's curated memory banks.

Serves a review/editor UI for the docs/ada-memory vault on mn01 behind
Caddy at /apps/obsidian/*. Read access is open on the tailnet; writes
(save/sync/commit) require X-API-Key when ADA_API_KEY is set.

Env:
  ADA_MEMORY_VAULT    vault root   (default ~/CascadeProjects/chaba-vault/docs/ada-memory)
  ADA_VAULT_REPO      repo root    (default ~/CascadeProjects/chaba-vault)
  ADA_MEMORY_MDDB_URL MDDB base    (default http://100.68.142.13:11023/v1)
  ADA_API_KEY         optional write gate (same convention as ada-ha services)
  ADA_DEPLOY          tailnet (default) | public — public requires ADA_API_KEY,
                      gates ALL /api reads behind it, and serves only banks
                      marked `public: true` in the banks registry SSOT.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

VAULT = Path(os.environ.get(
    "ADA_MEMORY_VAULT", "~/CascadeProjects/chaba-vault/docs/ada-memory"
)).expanduser()
REPO = Path(os.environ.get(
    "ADA_VAULT_REPO", "~/CascadeProjects/chaba-vault"
)).expanduser()
MDDB = os.environ.get("ADA_MEMORY_MDDB_URL", "http://100.68.142.13:11023/v1").rstrip("/")
API_KEY = os.environ.get("ADA_API_KEY") or ""
DEPLOY = os.environ.get("ADA_DEPLOY", "tailnet").strip().lower() or "tailnet"
INDEX_HTML = REPO / "stacks/web/public/apps/obsidian/index.html"
GRAPH_HTML = REPO / "stacks/web/public/apps/obsidian/graph.html"
SYNC_SCRIPT = REPO / "scripts/ada/sync-ada-memory-to-mddb.py"
BANKS_SSOT = REPO / "docs/ssot/apps/ssot.apps.ada-memory-banks.yml"

if DEPLOY == "public" and not API_KEY:
    raise SystemExit(
        "ADA_DEPLOY=public requires ADA_API_KEY — refusing to serve open "
        "reads on a public host"
    )

app = FastAPI(title="Ada Memory Vault")


def _bank_map() -> list[dict]:
    """[{bank, dir, collection, scope, title, writable, public}] — same
    {instance} expansion the sync script's load_bank_map() uses."""
    try:
        banks = yaml.safe_load(BANKS_SSOT.read_text()).get("banks") or {}
    except Exception:
        return []
    out = []
    for name, spec in banks.items():
        scope = spec.get("scope", "shared")
        coll = spec.get("mddb_collection") or ""
        instances = spec.get("instances") or []
        entry = {
            "bank": name,
            "title": spec.get("title") or name,
            "description": spec.get("description") or "",
            "writable": bool(spec.get("writable")),
            "public": bool(spec.get("public")),
        }
        if scope == "instance" and len(instances) > 1 and "{instance}" in coll:
            for inst in instances:
                out.append({**entry, "dir": f"{name}/{inst}",
                            "collection": coll.replace("{instance}", inst),
                            "scope": inst})
        elif scope == "instance":
            inst = instances[0] if instances else ""
            out.append({**entry, "dir": name,
                        "collection": coll.replace("{instance}", inst),
                        "scope": inst})
        else:
            out.append({**entry, "dir": name, "collection": coll,
                        "scope": "shared"})
    out.append({"bank": "inbox", "dir": "inbox", "collection": None,
                "scope": "", "writable": True, "public": False,
                "title": "Inbox",
                "description": "Voice-written notes awaiting review"})
    return out


def _visible_dirs() -> set[str]:
    """Vault dirs servable in the current deploy mode. tailnet: everything,
    including dirs not in the registry. public: registry dirs flagged
    public: true only (deny-by-default)."""
    if DEPLOY != "public":
        return set()  # sentinel: no filtering
    return {b["dir"] for b in _bank_map() if b["public"]}


def _bank_meta() -> tuple[list[str], dict]:
    """Sidebar order + per-dir info derived from the bank registry SSOT."""
    order, info = [], {}
    for b in _bank_map():
        order.append(b["dir"])
        info[b["dir"]] = {"title": b["title"], "description": b["description"],
                          "writable": b["writable"], "scope": b["scope"]}
    return order, info

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _check_write_auth(request: Request) -> None:
    if API_KEY and request.headers.get("x-api-key") != API_KEY:
        raise HTTPException(401, "missing or invalid X-API-Key")


def _check_read_auth(request: Request) -> None:
    """Reads are open on tailnet; ADA_DEPLOY=public gates every /api read
    behind the same X-API-Key as writes."""
    if DEPLOY == "public":
        _check_write_auth(request)


def _split(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2).strip()


def _safe_path(rel: str) -> Path:
    p = (VAULT / rel).resolve()
    if not str(p).startswith(str(VAULT.resolve()) + os.sep) or not p.name.endswith(".md"):
        raise HTTPException(400, f"invalid vault path: {rel!r}")
    return p


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML.read_text())


@app.get("/graph", response_class=HTMLResponse)
async def graph_page() -> HTMLResponse:
    return HTMLResponse(GRAPH_HTML.read_text())


def _folder(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _hidden_dir(rel: str) -> bool:
    """True when rel lives under a bank dir hidden in public deploy mode."""
    visible = _visible_dirs()
    return bool(visible) and _folder(rel) not in visible


@app.get("/api/tree")
async def tree(request: Request) -> dict:
    _check_read_auth(request)
    banks: dict[str, list[dict]] = {}
    for md in sorted(VAULT.rglob("*.md")):
        rel = md.relative_to(VAULT).as_posix()
        if md.name.startswith(("_", ".")) or md.name == "README.md" or _hidden_dir(rel):
            continue
        fm, body = _split(md.read_text())
        folder = _folder(rel)
        banks.setdefault(folder, []).append({
            "path": rel,
            "name": md.stem,
            "key": fm.get("key"),
            "kind": fm.get("kind"),
            "status": fm.get("status") or "active",
            "subject": fm.get("subject"),
            "chars": len(body),
        })
    order, meta = _bank_meta()
    extra = [d for d in banks if d not in order]
    return {"vault": str(VAULT), "banks": banks, "deploy": DEPLOY,
            "bank_order": order + extra, "bank_meta": meta}


@app.get("/api/note")
async def get_note(path: str, request: Request) -> dict:
    _check_read_auth(request)
    p = _safe_path(path)
    if not p.exists() or _hidden_dir(path):
        raise HTTPException(404, f"no such note: {path}")
    raw = p.read_text()
    fm, body = _split(raw)
    return {"path": path, "frontmatter": fm, "body": body, "raw": raw}


class SaveRequest(BaseModel):
    path: str
    raw: str


@app.post("/api/note")
async def save_note(req: SaveRequest, request: Request) -> dict:
    _check_write_auth(request)
    p = _safe_path(req.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(req.raw)
    return {"ok": True, "path": req.path}


@app.get("/api/status")
async def status(request: Request) -> dict:
    _check_read_auth(request)
    dirty = ""
    if (REPO / ".git").exists():
        out = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain", "--", "docs/ada-memory"],
            capture_output=True, text=True, timeout=10,
        )
        dirty = out.stdout.strip()
    visible = _visible_dirs()
    top_visible = {d.split("/", 1)[0] for d in visible} if visible else None
    counts = {d.name: sum(1 for f in d.glob("*.md")
                          if not f.name.startswith(("_", ".")) and f.name != "README.md")
              for d in sorted(VAULT.iterdir())
              if d.is_dir() and (top_visible is None or d.name in top_visible)}
    hidden = sum(1 for b in _bank_map() if not b["public"]) if visible else 0
    return {"vault": str(VAULT), "repo": str(REPO), "dirty": dirty,
            "counts": counts, "deploy": DEPLOY, "hidden_banks": hidden}


def _m1(meta: dict, k: str):
    """Unwrap MDDB list-meta or frontmatter scalar -> scalar|None."""
    v = (meta or {}).get(k)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _ml(meta: dict, k: str) -> list[str]:
    v = (meta or {}).get(k)
    if v is None:
        return []
    return [str(x) for x in (v if isinstance(v, list) else [v])]


_SIM_CACHE: dict[str, tuple[float, list]] = {}  # nid -> (ts, [(tid, score)])
_SIM_TTL = 3600


async def _similar_for(cli: httpx.AsyncClient, sem: asyncio.Semaphore,
                       nid: str, coll: str, text: str) -> list[tuple[str, float]]:
    hit = _SIM_CACHE.get(nid)
    if hit and time.time() - hit[0] < _SIM_TTL:
        return hit[1]
    async with sem:
        try:
            r = await cli.post(f"{MDDB}/vector-search", json={
                "collection": coll, "query": text[:200], "topK": 4,
                "threshold": 0.75})
            r.raise_for_status()
            out = [
                (f"{coll}:{(it.get('document') or {}).get('key')}",
                 it.get("score") or 0.0)
                for it in (r.json().get("results") or [])
            ]
            out = [(t, s) for t, s in out if t != nid]
        except Exception:
            out = []
    _SIM_CACHE[nid] = (time.time(), out)
    return out


@app.get("/api/graph")
async def api_graph(request: Request, banks: str = "", status: str = "",
                    similar: int = 0, hubs: int = 1) -> dict:
    """Merged vault+MDDB knowledge graph. Nodes keyed {collection}:{key};
    sync flag shows vault/MDDB membership drift. See ssot.apps.ada-memory-banks
    Visibility section for the public: filter."""
    _check_read_auth(request)
    bmap = _bank_map()
    visible = _visible_dirs()
    entries = [b for b in bmap if not visible or b["dir"] in visible]
    if banks:
        want = {s.strip() for s in banks.split(",") if s.strip()}
        entries = [b for b in entries
                   if b["bank"] in want or (b["collection"] or "") in want]
    dir_entry = {b["dir"]: b for b in entries}
    hidden_colls = {
        b["collection"] for b in bmap
        if b["collection"] and b not in entries
    }

    nodes: dict[str, dict] = {}
    raw: dict[str, dict] = {}
    bodies: dict[str, str] = {}

    def upsert(nid: str, fields: dict, meta: dict, body: str) -> None:
        n = nodes.setdefault(nid, {
            "id": nid, "key": fields["key"], "collection": fields["collection"],
            "bank": fields["bank"], "label": fields["key"].rsplit("/", 1)[-1],
        })
        for k, v in fields.items():
            if v is not None and n.get(k) is None:
                n[k] = v
        bodies.setdefault(nid, body)
        rm = raw.setdefault(nid, {})
        for k in ("subject", "supersedes", "superseded_by", "related",
                  "source_keys", "applies_to"):
            vals = _ml(meta, k) if k != "subject" else ([str(_m1(meta, k))] if _m1(meta, k) else [])
            rm.setdefault(k, vals)

    # --- vault pass ---
    for md in sorted(VAULT.rglob("*.md")):
        rel = md.relative_to(VAULT).as_posix()
        if md.name.startswith(("_", ".")) or md.name == "README.md" or _hidden_dir(rel):
            continue
        folder = _folder(rel)
        b = dir_entry.get(folder)
        coll = (b or {}).get("collection") or folder or "vault"
        bank = (b or {}).get("bank") or folder.split("/", 1)[0] or "vault"
        fm, body = _split(md.read_text())
        if not fm:
            continue
        key = str(fm.get("key") or f"{bank}/{md.stem}")
        nid = f"{coll}:{key}"
        upsert(nid, {
            "key": key, "collection": coll, "bank": bank, "path": rel,
            "kind": str(fm.get("kind") or "note"),
            "status": str(fm.get("status") or "active"),
            "subject": fm.get("subject"),
            "scope": (b or {}).get("scope"),
            "written_by": _m1(fm, "written_by"),
            "confidence": fm.get("confidence"),
            "use_count": fm.get("use_count"),
            "outcome": _m1(fm, "outcome"),
            "verdict": _m1(fm, "verdict"),
            "last_verified": str(fm.get("last_verified") or "") or None,
        }, fm, body)
        nodes[nid]["sync"] = "inbox" if folder == "inbox" else "vault_only"

    # --- MDDB pass (collections fetched in parallel) ---
    mddb_fail: list[str] = []
    sem = asyncio.Semaphore(6)

    async def fetch_coll(b: dict):
        coll = b["collection"]
        if not coll:
            return b, []
        async with sem:
            try:
                r = await cli.post(f"{MDDB}/search",
                                   json={"collection": coll, "limit": 1000})
                r.raise_for_status()
                return b, r.json()
            except Exception:
                mddb_fail.append(coll)
                return b, []

    async with httpx.AsyncClient(timeout=20) as cli:
        for b, docs in await asyncio.gather(*(fetch_coll(b) for b in entries)):
            for doc in docs or []:
                key = str(doc.get("key") or "")
                if not key:
                    continue
                meta = doc.get("meta") or {}
                body = str(doc.get("contentMd") or "")
                # kb-* docs keep fields like `related` only in the frontmatter
                # embedded inside contentMd — meta wins on overlap.
                doc_fm, _ = _split(body)
                merged = {**doc_fm, **meta}
                nid = f"{coll}:{key}"
                upsert(nid, {
                    "key": key, "collection": coll, "bank": b["bank"],
                    "kind": _m1(merged, "kind") or "note",
                    "status": _m1(merged, "status") or "active",
                    "subject": _m1(merged, "subject"),
                    "scope": _m1(merged, "scope") or b["scope"],
                    "written_by": _m1(merged, "written_by"),
                    "confidence": _m1(merged, "confidence"),
                    "use_count": _m1(merged, "use_count"),
                    "outcome": _m1(merged, "outcome"),
                    "verdict": _m1(merged, "verdict"),
                    "last_verified": _m1(merged, "last_verified"),
                }, merged, body)
                n = nodes[nid]
                n["sync"] = "synced" if n.get("path") else "mddb_only"
                if _m1(merged, "title"):
                    n["label"] = str(_m1(merged, "title"))

    # --- status filter ---
    if status and status != "all":
        nodes = {i: n for i, n in nodes.items() if n.get("status") == status}
        raw = {i: r for i, r in raw.items() if i in nodes}

    # --- edges ---
    links: list[dict] = []
    seen: set[tuple] = set()

    def add_edge(s: str, t: str, typ: str, **kw) -> None:
        if s == t or (s, t, typ) in seen:
            return
        seen.add((s, t, typ))
        links.append({"source": s, "target": t, "type": typ, **kw})

    def resolve(coll: str, key: str, typ: str) -> str | None:
        """Resolve a key reference in coll to a node id; stub or drop."""
        tid = f"{coll}:{key}"
        if tid in nodes:
            return tid
        if coll in hidden_colls:
            return None  # target bank hidden — drop silently, don't leak key
        nodes[tid] = {"id": tid, "key": key, "collection": coll,
                      "bank": "", "label": key.rsplit("/", 1)[-1],
                      "missing": True}
        return tid

    stem_idx: dict[str, dict[str, str]] = {}
    for nid, n in nodes.items():
        stem_idx.setdefault(n["collection"], {})[n["label"]] = nid

    for nid, rm in raw.items():
        coll = nodes[nid]["collection"]
        for k in rm.get("supersedes", []):
            t = resolve(coll, k, "supersedes")
            if t:
                add_edge(t, nid, "supersedes")  # old -> new
        for k in rm.get("superseded_by", []):
            t = resolve(coll, k, "superseded_by")
            if t:
                add_edge(nid, t, "supersedes")
        for k in rm.get("source_keys", []):
            t = resolve(coll, k, "rollup")
            if t is None:
                continue
            if nodes.get(t, {}).get("missing"):
                # rollup sources can live in other collections — try a
                # global key match before accepting the stub.
                matches = [i for i in nodes if i.endswith(f":{k}")
                           and not nodes[i].get("missing")]
                if len(matches) == 1:
                    del nodes[t]
                    t = matches[0]
            add_edge(nid, t, "rollup")
        for relname in rm.get("related", []):
            stem = relname.rsplit("/", 1)[-1].removesuffix(".md")
            t = stem_idx.get(coll, {}).get(stem)
            if t:
                add_edge(nid, t, "related")

    # --- subject/entity structure: hub nodes (default) or cliques ---
    for field, prefix, hub_type, clique_type in (
        ("subject", "subject", "subject", "same_subject"),
        ("applies_to", "entity", "applies_to", "same_entity"),
    ):
        groups: dict[str, list[str]] = {}
        for nid, rm in raw.items():
            for v in (rm.get(field) or []):
                groups.setdefault(v, []).append(nid)
        for val, members in groups.items():
            if len(members) < 2:
                continue
            if hubs:
                hid = f"{prefix}:{val}"
                nodes[hid] = {"id": hid, "hub": field, "label": val}
                for m in members:
                    add_edge(m, hid, hub_type, label=val)
            else:
                for i, a in enumerate(members):
                    for c in members[i + 1:]:
                        add_edge(a, c, clique_type, label=val)

    # --- optional vector-similarity edges (cached 1h) ---
    similarity = False
    if similar:
        coll_set = {b["collection"] for b in entries if b["collection"]}
        sem = asyncio.Semaphore(6)
        async with httpx.AsyncClient(timeout=15) as cli:
            ids = [nid for nid, n in nodes.items()
                   if n["collection"] in coll_set and bodies.get(nid)]
            results = dict(zip(ids, await asyncio.gather(*(
                _similar_for(cli, sem, nid, nodes[nid]["collection"],
                             bodies[nid])
                for nid in ids))))
        for nid, hits in results.items():
            for tid, score in hits:
                if tid in nodes:
                    similarity = True
                    a, b2 = sorted([nid, tid])
                    add_edge(a, b2, "similar", weight=round(score, 3))

    counts = {"synced": 0, "mddb_only": 0, "vault_only": 0, "inbox": 0}
    for n in nodes.values():
        if n.get("sync") in counts:
            counts[n["sync"]] += 1
    real_colls = sum(1 for b in entries if b["collection"])
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "context": {"deploy": DEPLOY, "auth": DEPLOY == "public"},
        "sources": {
            "vault": True,
            "mddb": len(mddb_fail) < real_colls,
            "similarity": similarity,
        },
        "banks": {
            (b["collection"] or b["dir"]): {
                "bank": b["bank"], "title": b["title"],
                "scope": b["scope"], "writable": b["writable"],
            } for b in entries
        },
        "nodes": list(nodes.values()),
        "links": links,
        "stats": {
            "nodes": len(nodes), "links": len(links), **counts,
            "dangling": sum(1 for n in nodes.values() if n.get("missing")),
            "hidden_banks": (
                sum(1 for b in _bank_map() if not b["public"]) if visible else 0
            ),
        },
    }
    if mddb_fail:
        out["warning"] = (
            "mddb unreachable — vault-only view"
            if len(mddb_fail) == real_colls
            else "mddb failed for: " + ", ".join(mddb_fail)
        )
    return out


def _run(cmd: list[str]) -> dict:
    out = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=60)
    return {"ok": out.returncode == 0, "output": (out.stdout + out.stderr).strip()}


@app.post("/api/sync")
async def sync(request: Request) -> dict:
    """Push vault → MDDB (runs the sync script; whole vault, idempotent)."""
    _check_write_auth(request)
    return _run(["python3", str(SYNC_SCRIPT), "--mddb", MDDB])


class CommitRequest(BaseModel):
    message: str = "vault edit via apps/obsidian"


@app.post("/api/commit")
async def commit(req: CommitRequest, request: Request) -> dict:
    """Sync vault -> MDDB, then queue the git commit: this runtime copy isn't
    a git checkout — tony-omen's hourly ada-memory-pull.timer pulls the vault,
    commits and pushes it. personal/* stays local by design."""
    _check_write_auth(request)
    sync = _run(["python3", str(SYNC_SCRIPT), "--mddb", MDDB])
    return {
        "ok": sync["ok"],
        "commit": "queued — ada-memory-pull.timer on tony-omen commits hourly "
                  "(personal/* is gitignored, never committed)",
        "push": {"ok": True, "output": "via timer"},
        "sync": sync["output"][-800:],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8004, log_level="info")
