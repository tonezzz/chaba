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
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

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
MDDB = os.environ.get("ADA_MEMORY_MDDB_URL", "http://100.68.142.13:11023/v1")
API_KEY = os.environ.get("ADA_API_KEY") or ""
INDEX_HTML = REPO / "stacks/web/public/apps/obsidian/index.html"
SYNC_SCRIPT = REPO / "scripts/ada/sync-ada-memory-to-mddb.py"
BANKS_SSOT = REPO / "docs/ssot/apps/ssot.apps.ada-memory-banks.yml"

app = FastAPI(title="Ada Memory Vault")


def _bank_meta() -> tuple[list[str], dict]:
    """Sidebar order + per-dir info derived from the bank registry SSOT —
    the same dir mapping the sync script uses (single-instance banks are
    flat dirs, multi-instance banks get name/<instance> subdirs)."""
    try:
        banks = yaml.safe_load(BANKS_SSOT.read_text()).get("banks") or {}
    except Exception:
        return [], {}
    order, info = [], {}
    for name, spec in banks.items():
        instances = spec.get("instances") or []
        meta = {
            "title": spec.get("title") or name,
            "description": spec.get("description") or "",
            "writable": bool(spec.get("writable")),
            "scope": spec.get("scope") or "shared",
        }
        if spec.get("scope") == "instance" and len(instances) > 1:
            for inst in instances:
                d = f"{name}/{inst}"
                order.append(d)
                info[d] = {**meta, "title": f"{meta['title']} ({inst})"}
        else:
            order.append(name)
            info[name] = meta
    order.append("inbox")
    info["inbox"] = {"title": "Inbox", "description": "Voice-written notes awaiting review", "writable": True, "scope": ""}
    return order, info

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _check_write_auth(request: Request) -> None:
    if API_KEY and request.headers.get("x-api-key") != API_KEY:
        raise HTTPException(401, "missing or invalid X-API-Key")


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


@app.get("/api/tree")
async def tree() -> dict:
    banks: dict[str, list[dict]] = {}
    for md in sorted(VAULT.rglob("*.md")):
        rel = md.relative_to(VAULT).as_posix()
        if md.name.startswith(("_", ".")) or md.name == "README.md":
            continue
        fm, body = _split(md.read_text())
        folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
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
    return {"vault": str(VAULT), "banks": banks,
            "bank_order": order + extra, "bank_meta": meta}


@app.get("/api/note")
async def get_note(path: str) -> dict:
    p = _safe_path(path)
    if not p.exists():
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
async def status() -> dict:
    dirty = ""
    if (REPO / ".git").exists():
        out = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain", "--", "docs/ada-memory"],
            capture_output=True, text=True, timeout=10,
        )
        dirty = out.stdout.strip()
    counts = {d.name: sum(1 for f in d.glob("*.md")
                          if not f.name.startswith(("_", ".")) and f.name != "README.md")
              for d in sorted(VAULT.iterdir()) if d.is_dir()}
    return {"vault": str(VAULT), "repo": str(REPO), "dirty": dirty, "counts": counts}


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
    _check_write_auth(request)
    add = _run(["git", "add", "docs/ada-memory"])
    if not add["ok"]:
        return add
    ci = _run(["git", "commit", "-m", req.message or "vault edit via apps/obsidian"])
    push = _run(["git", "push"]) if ci["ok"] else {"ok": False, "output": "skipped"}
    return {"ok": ci["ok"], "commit": ci["output"], "push": push}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8004, log_level="info")
