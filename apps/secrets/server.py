#!/usr/bin/env python3
"""apps/secrets — Secrets Console backend.

One place to enter credentials once and have them written to every slot
(env-file vars, whole-file secrets, inline unit Environment= lines) on
every host, with consumer restarts and fingerprint parity checks.
Plan: docs/ada-memory/tony-projects/secrets-console-plan.md.

Values are never returned — reads yield sha256 fingerprints + mtimes so
drift is visible without exposing secrets. Mutations and vault reveals
require X-API-Key (SECRETS_CONSOLE_API_KEY); unset => read-only.

Env:
  SECRETS_SSOT              manifest (default <repo>/docs/ssot/infrastructure/ssot.secrets.yml)
  SECRETS_LOCAL_HOST        manifest host name for this machine (default tony-dell)
  SECRETS_CONSOLE_API_KEY   write/vault-reveal gate; unset => read-only
  SECRETS_READONLY          "1" forces read-only even if the key is set
  SECRETS_VAULT             login vault file (default ~/.local/share/secrets-vault/vault.json.enc)
  SECRETS_VAULT_KEY_FILE    Fernet key file (default ~/.local/share/secrets-vault/key)
  SECRETS_VAULT_REPLICA     scp target for post-write replication
                            (e.g. tony-omen:~/.local/share/secrets-vault/)
  ADA_DEPLOY                must not be "public" — this app refuses to run there
  PORT                      listen port (default 8005)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

log = logging.getLogger("secrets")

REPO = Path(__file__).resolve().parents[2]
MANIFEST = Path(os.environ.get(
    "SECRETS_SSOT", str(REPO / "docs/ssot/infrastructure/ssot.secrets.yml")
)).expanduser()
LOCAL_HOST = os.environ.get("SECRETS_LOCAL_HOST", "tony-dell")
API_KEY = os.environ.get("SECRETS_CONSOLE_API_KEY") or ""
READONLY = os.environ.get("SECRETS_READONLY") == "1" or not API_KEY
INDEX_HTML = REPO / "stacks/web/public/apps/secrets/index.html"
VAULT_FILE = Path(os.environ.get(
    "SECRETS_VAULT", "~/.local/share/secrets-vault/vault.json.enc"
)).expanduser()
KEY_FILE = Path(os.environ.get(
    "SECRETS_VAULT_KEY_FILE", "~/.local/share/secrets-vault/key"
)).expanduser()
VAULT_REPLICA = os.environ.get("SECRETS_VAULT_REPLICA", "")
AUDIT_LOG = VAULT_FILE.parent / "audit.log"
EVENT_LOG = "/home/tony/.config/home-assistant/scripts/chaba-event-log.py"

if os.environ.get("ADA_DEPLOY", "").strip().lower() == "public":
    raise SystemExit(
        "secrets-console must never run on a public host — refusing to start"
    )

app = FastAPI(title="Secrets Console")


def _require_key(request: Request) -> None:
    if READONLY:
        raise HTTPException(503, "console is read-only (SECRETS_CONSOLE_API_KEY unset or SECRETS_READONLY=1)")
    if request.headers.get("x-api-key") != API_KEY:
        raise HTTPException(401, "missing or invalid X-API-Key")


def _audit(action: str, detail: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": action, **detail,
        }) + "\n")


def _emit(title: str, body: str, severity: str = "warn") -> None:
    """chaba-event, best-effort. Local on tony-dell, ssh elsewhere."""
    payload = json.dumps({
        "title": title, "category": "secrets-console", "source": "secrets-console",
        "severity": severity, "requires_response": severity == "fail",
        "body": body[:600], "confidence": 1.0,
    })
    cmd = ["python3", EVENT_LOG, "add", "-"]
    if LOCAL_HOST != "tony-dell":
        cmd = ["ssh", "tony-dell"] + cmd
    try:
        subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=20)
    except Exception:
        pass


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text()) or {}


def _cred(cid: str) -> dict:
    for c in _manifest().get("credentials") or []:
        if c.get("id") == cid:
            return c
    raise HTTPException(404, f"no credential {cid!r}")


# -- slot IO -----------------------------------------------------------------

# Runs under `python3 -c` on the target host (local or via ssh). Prints a
# JSON result; the value travels over ssh stdin for writes, never argv.
_REMOTE_READ = r'''
import sys, os, re, json, hashlib
file, var, typ = os.path.expanduser(sys.argv[1]), sys.argv[2], sys.argv[3]
out = {"present": False}
try:
    st = os.stat(file)
    out["mtime"] = int(st.st_mtime)
    if typ == "file":
        out["present"] = True
        out["fingerprint"] = hashlib.sha256(open(file, "rb").read()).hexdigest()[:12]
    else:
        pat = (r"(?:^|[\s\"'])" + re.escape(var) + r"=(?:\"([^\"]*)\"|'([^']*)'|([^\s\"']*))"
               if typ == "unit" else
               r"^\s*(?:export\s+)?" + re.escape(var) + r"\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(.*)$)")
        val = None
        for line in open(file, errors="replace"):
            if typ == "unit" and "Environment" not in line:
                continue
            m = re.search(pat, line)
            if m:
                val = next(g for g in m.groups() if g is not None)
        if val is not None:
            out["present"] = True
            out["fingerprint"] = hashlib.sha256(val.encode()).hexdigest()[:12]
            out["len"] = len(val)
except FileNotFoundError:
    pass
print(json.dumps(out))
'''

_REMOTE_WRITE = r'''
import sys, os, re, json, time, shutil
file, var, typ = os.path.expanduser(sys.argv[1]), sys.argv[2], sys.argv[3]
value = sys.stdin.read()
os.makedirs(os.path.dirname(file) or ".", exist_ok=True)
if os.path.exists(file):
    shutil.copy2(file, file + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
if typ == "file":
    new = value
else:
    try:
        old = open(file).read()
    except FileNotFoundError:
        old = ""
    if typ == "unit":
        pat = re.compile(r"(" + re.escape(var) + r"=)(?:\"[^\"]*\"|'[^']*'|[^\s\"']*)")
        new = (pat.sub(lambda m: m.group(1) + value, old) if pat.search(old)
               else old + ("" if not old or old.endswith("\n") else "\n")
                    + f'Environment="{var}={value}"\n')
    else:
        pat = re.compile(r"(?m)^(\s*(?:export\s+)?" + re.escape(var) + r"\s*=).*$")
        new = (pat.sub(lambda m: m.group(1) + value, old) if pat.search(old)
               else old + ("" if not old or old.endswith("\n") else "\n")
                    + f"{var}={value}\n")
tmp = file + ".tmp"
with open(tmp, "w") as f:
    f.write(new)
os.chmod(tmp, 0o600)
os.replace(tmp, file)
print(json.dumps({"ok": True}))
'''


async def _run_host(host: str, script: str, args: list[str],
                    stdin: bytes | None = None, timeout: float = 25) -> dict:
    """Run a python -c script locally or over ssh. Returns parsed JSON or
    {error: ...} — slot IO never raises."""
    cmd = (["python3", "-c", script] + args if host == LOCAL_HOST
           else ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
                 host, "python3", "-c", script] + args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(
            proc.communicate(stdin), timeout=timeout)
        if proc.returncode != 0:
            return {"error": (err.decode(errors="replace") or "failed").strip()[:300]}
        return json.loads(out.decode())
    except Exception as exc:
        return {"error": str(exc)[:300]}


async def _slot_status(slot: dict) -> dict:
    host = str(slot.get("host") or "")
    typ = str(slot.get("type") or "var")
    res = await _run_host(host, _REMOTE_READ,
                          [str(slot.get("file") or ""), str(slot.get("var") or ""), typ])
    return {**{k: slot.get(k) for k in ("host", "file", "var", "type", "note")},
            "type": typ, **res}


def _parity(slots: list[dict]) -> str:
    fps = {s.get("fingerprint") for s in slots if s.get("present")}
    if not fps:
        return "empty" if all(s.get("present") is False for s in slots) else "error"
    return "consistent" if len(fps) == 1 else "DRIFT"


# -- registry API ------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "readonly": READONLY, "manifest": str(MANIFEST)}


@app.get("/api/credentials")
async def list_credentials() -> dict:
    creds = []
    for c in _manifest().get("credentials") or []:
        slots = await asyncio.gather(*[_slot_status(s) for s in c.get("slots") or []])
        creds.append({
            "id": c.get("id"), "title": c.get("title"), "kind": c.get("kind"),
            "sensitivity": c.get("sensitivity"),
            "issuer": c.get("issuer"), "rotate": c.get("rotate"),
            "consumers": c.get("consumers") or [],
            "slots": list(slots), "parity": _parity(list(slots)),
        })
    return {"credentials": creds, "readonly": READONLY}


@app.get("/api/credentials/{cid}")
async def get_credential(cid: str) -> dict:
    c = _cred(cid)
    slots = await asyncio.gather(*[_slot_status(s) for s in c.get("slots") or []])
    return {**c, "slots": list(slots), "parity": _parity(list(slots))}


class SetBody(BaseModel):
    value: str
    restart: bool = False


@app.post("/api/credentials/{cid}/set")
async def set_credential(cid: str, body: SetBody, request: Request) -> dict:
    _require_key(request)
    c = _cred(cid)
    if not body.value:
        raise HTTPException(400, "empty value")
    results = []
    for s in c.get("slots") or []:
        host = str(s.get("host") or "")
        typ = str(s.get("type") or "var")
        res = await _run_host(
            host, _REMOTE_WRITE,
            [str(s.get("file") or ""), str(s.get("var") or ""), typ],
            stdin=body.value.encode())
        results.append({"host": host, "file": s.get("file"),
                        "var": s.get("var"), **res})
        if typ == "unit":
            await _run_cmd(host, ["systemctl", "--user", "daemon-reload"])
    restarts = []
    if body.restart:
        for cons in c.get("consumers") or []:
            r = await _run_cmd(str(cons.get("host") or ""),
                               ["systemctl", "--user", "restart",
                                str(cons.get("unit") or "")])
            restarts.append({**cons, **r})
    slots = await asyncio.gather(*[_slot_status(s) for s in c.get("slots") or []])
    parity = _parity(list(slots))
    _audit("set", {"credential": cid, "restart": body.restart,
                   "parity": parity,
                   "slots_ok": sum(1 for r in results if r.get("ok"))})
    _emit(f"credential set: {cid}",
          f"{sum(1 for r in results if r.get('ok'))}/{len(results)} slots written, "
          f"parity={parity}, restarts={len(restarts)}")
    return {"id": cid, "results": results, "restarts": restarts,
            "parity": parity, "slots": list(slots)}


@app.post("/api/credentials/{cid}/verify")
async def verify_credential(cid: str) -> dict:
    c = _cred(cid)
    slots = await asyncio.gather(*[_slot_status(s) for s in c.get("slots") or []])
    return {"id": cid, "slots": list(slots), "parity": _parity(list(slots))}


async def _run_cmd(host: str, cmd: list[str], timeout: float = 30) -> dict:
    full = cmd if host == LOCAL_HOST else ["ssh", "-o", "BatchMode=yes", host] + cmd
    try:
        proc = await asyncio.create_subprocess_exec(
            *full, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {"ok": proc.returncode == 0,
                "err": err.decode(errors="replace").strip()[:200] or None}
    except Exception as exc:
        return {"ok": False, "err": str(exc)[:200]}


# -- login vault -------------------------------------------------------------

def _fernet():
    from cryptography.fernet import Fernet
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_bytes(Fernet.generate_key())
        os.chmod(KEY_FILE, 0o600)
    return Fernet(KEY_FILE.read_bytes().strip())


def _vault_load() -> dict:
    if not VAULT_FILE.exists():
        return {"entries": []}
    try:
        return json.loads(_fernet().decrypt(VAULT_FILE.read_bytes()))
    except Exception as exc:
        raise HTTPException(500, f"vault decrypt failed: {exc}")


async def _vault_save(data: dict) -> None:
    VAULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    enc = _fernet().encrypt(json.dumps(data).encode())
    tmp = VAULT_FILE.with_suffix(".tmp")
    tmp.write_bytes(enc)
    os.chmod(tmp, 0o600)
    os.replace(tmp, VAULT_FILE)
    if VAULT_REPLICA:
        host, _, rpath = VAULT_REPLICA.partition(":")
        rdir = os.path.dirname(rpath) or "~/.local/share/secrets-vault"
        await _run_cmd(host, ["mkdir", "-p", rdir])
        proc = await asyncio.create_subprocess_exec(
            "scp", "-q", str(VAULT_FILE), str(KEY_FILE), VAULT_REPLICA,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()


def _public_entry(e: dict) -> dict:
    return {k: e.get(k) for k in
            ("id", "title", "username", "url", "tags", "notes", "updated")}


class VaultEntry(BaseModel):
    title: str
    username: str | None = None
    url: str | None = None
    secret: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


@app.get("/api/vault")
async def vault_list() -> dict:
    return {"entries": [_public_entry(e) for e in _vault_load()["entries"]]}


@app.post("/api/vault/{eid}/reveal")
async def vault_reveal(eid: str, request: Request) -> dict:
    _require_key(request)
    for e in _vault_load()["entries"]:
        if e.get("id") == eid:
            _audit("vault-reveal", {"id": eid})
            return {"id": eid, "secret": e.get("secret"),
                    "username": e.get("username")}
    raise HTTPException(404, "no such entry")


@app.post("/api/vault")
async def vault_add(entry: VaultEntry, request: Request) -> dict:
    _require_key(request)
    data = _vault_load()
    eid = re.sub(r"[^a-z0-9-]+", "-", entry.title.lower()).strip("-") or "entry"
    eid = f"{eid}-{int(time.time())}"
    e = {"id": eid, **entry.model_dump(exclude_none=True),
         "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    data["entries"].append(e)
    await _vault_save(data)
    _audit("vault-add", {"id": eid})
    _emit("vault entry added", f"login vault: {entry.title}", "info")
    return _public_entry(e)


@app.put("/api/vault/{eid}")
async def vault_update(eid: str, entry: VaultEntry, request: Request) -> dict:
    _require_key(request)
    data = _vault_load()
    for e in data["entries"]:
        if e.get("id") == eid:
            for k, v in entry.model_dump(exclude_none=True).items():
                e[k] = v
            e["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            await _vault_save(data)
            _audit("vault-update", {"id": eid})
            return _public_entry(e)
    raise HTTPException(404, "no such entry")


@app.delete("/api/vault/{eid}")
async def vault_delete(eid: str, request: Request) -> dict:
    _require_key(request)
    data = _vault_load()
    before = len(data["entries"])
    data["entries"] = [e for e in data["entries"] if e.get("id") != eid]
    if len(data["entries"]) == before:
        raise HTTPException(404, "no such entry")
    await _vault_save(data)
    _audit("vault-delete", {"id": eid})
    return {"ok": True}


# -- UI ----------------------------------------------------------------------

@app.get("/", response_class=FileResponse)
async def index():
    return INDEX_HTML


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", "8005"))
    # Tailscale IP + loopback only — never 0.0.0.0 on this app.
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")
