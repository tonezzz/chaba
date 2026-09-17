# Google NotebookLM REST API wrapper
# Based on https://github.com/gnh1201/notebooklm-rest-api (Namhyeon Go)
# Extended: scoped API keys, /health/auth, idempotency, write queue,
#           in-container auth keepalive, source lifecycle pruning.
import asyncio
import json
import os
import sys
import time
import uuid
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional, Literal, Dict

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from notebooklm import NotebookLMClient, RPCError


# ----------------------------
# Config / Security
# ----------------------------
_API_KEY_SINGLE = os.environ.get("NOTEBOOKLM_REST_API_KEY", "")
_API_KEYS_MULTI = {k.strip() for k in os.environ.get("NOTEBOOKLM_REST_API_KEYS", "").split(",") if k.strip()}
API_KEYS = _API_KEYS_MULTI or ({_API_KEY_SINGLE} if _API_KEY_SINGLE else set())

# Scoped keys: {"<api-key>": {"name": "ada-michael", "notebooks": ["<id>", ...],
#                             "read_only": false}}
# Keys listed here are restricted; valid keys NOT listed get full access.
try:
    KEY_SCOPES: Dict[str, Dict[str, Any]] = json.loads(
        os.environ.get("NOTEBOOKLM_REST_KEY_SCOPES", "") or "{}"
    )
except json.JSONDecodeError:
    KEY_SCOPES = {}

AUTH_STORAGE_PATH = os.environ.get("NOTEBOOKLM_STORAGE_PATH")  # optional override

# Keepalive: run `notebooklm auth refresh --verify` on this interval (seconds).
# notebooklm-py recommends 15-20 min so __Secure-1PSIDTS stays rotated.
KEEPALIVE_INTERVAL = int(os.environ.get("NOTEBOOKLM_KEEPALIVE_INTERVAL", "900"))
HEADLESS_REAUTH = os.environ.get("NOTEBOOKLM_HEADLESS_REAUTH", "") == "1"

# Write queue: buffer failed source writes, flush when auth recovers.
QUEUE_WRITES_DEFAULT = os.environ.get("NOTEBOOKLM_QUEUE_WRITES", "1") == "1"

_DATA_DIR = os.path.dirname(AUTH_STORAGE_PATH) if AUTH_STORAGE_PATH else tempfile.gettempdir()
_IDEM_PATH = os.path.join(_DATA_DIR, "idempotency.json")
_QUEUE_PATH = os.path.join(_DATA_DIR, "write_queue.json")
_IDEM_TTL = 86400          # 24h
_IDEM_MAX = 500
_HEALTH_CACHE_TTL = 60     # seconds between auth probes


def require_api_key(request: Request, x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    # GET /health* is unauthenticated so external monitors can probe liveness
    # and auth status; they expose only ok/expired, no data. POST /health/auth/refresh
    # stays key-gated.
    if request.method == "GET" and request.url.path.startswith("/health"):
        return
    if API_KEYS and x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
    scope = KEY_SCOPES.get(x_api_key or "")
    if not scope:
        return  # admin / unrestricted key
    request.state.key_scope = scope
    nb_id = request.path_params.get("notebook_id")
    allowed = scope.get("notebooks", ["*"])
    if nb_id and "*" not in allowed and nb_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"API key '{scope.get('name', 'scoped')}' is not allowed on notebook {nb_id}",
        )
    if scope.get("read_only") and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise HTTPException(status_code=403, detail=f"API key '{scope.get('name', 'scoped')}' is read-only")


# Shared client: per-request from_storage + open/close costs ~2-3s. Cache one
# opened client and rebuild when storage_state.json changes on disk (the auth
# keepalive rewrites it) or after any request error.
_shared_client: Optional[NotebookLMClient] = None
_shared_client_mtime: float = -1.0
_client_lock = asyncio.Lock()


class _SharedClientCtx:
    """async-with shim over the shared client: yields it without closing.

    Any exception inside the request body drops the shared client so the next
    request rebuilds it from storage.
    """

    def __init__(self, inner: NotebookLMClient) -> None:
        self._inner = inner

    def __getattr__(self, name: str):
        # Handlers use `async with client:` without rebinding, so proxy
        # attribute access (client.chat, client.sources, ...) to the inner
        # client.
        return getattr(self._inner, name)

    async def __aenter__(self) -> NotebookLMClient:
        return self._inner

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        global _shared_client
        if exc is not None and _shared_client is self._inner:
            _shared_client = None
            try:
                asyncio.create_task(self._inner.close())
            except Exception:
                pass
        return False


def _storage_mtime() -> float:
    if not AUTH_STORAGE_PATH:
        return -1.0
    try:
        return os.stat(AUTH_STORAGE_PATH).st_mtime
    except OSError:
        return -1.0


async def get_client():
    """Shared opened client; rebuilt when storage changes on disk."""
    global _shared_client, _shared_client_mtime
    if _shared_client is not None and _storage_mtime() == _shared_client_mtime:
        return _SharedClientCtx(_shared_client)
    async with _client_lock:
        mtime = _storage_mtime()
        if _shared_client is None or mtime != _shared_client_mtime:
            try:
                client = await (
                    NotebookLMClient.from_storage(AUTH_STORAGE_PATH)
                    if AUTH_STORAGE_PATH
                    else NotebookLMClient.from_storage()
                )
                await client.__aenter__()
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to initialize NotebookLM client: {e}",
                )
            old = _shared_client
            _shared_client = client
            _shared_client_mtime = mtime
            if old is not None:
                try:
                    asyncio.create_task(old.close())
                except Exception:
                    pass
    return _SharedClientCtx(_shared_client)


async def _close_shared_client() -> None:
    global _shared_client
    if _shared_client is not None:
        try:
            await _shared_client.close()
        except Exception:
            pass
        _shared_client = None


def map_rpc_error(e: RPCError) -> HTTPException:
    msg = str(e)
    if "401" in msg or "403" in msg or "auth" in msg.lower():
        return HTTPException(status_code=401, detail=msg)
    if "rate" in msg.lower() or "429" in msg:
        return HTTPException(status_code=429, detail=msg)
    return HTTPException(status_code=502, detail=msg)


# ----------------------------
# Small JSON stores (idempotency + write queue)
# ----------------------------
_store_lock = asyncio.Lock()


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, obj) -> None:
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, default=str)
    os.replace(tmp, path)


async def _idem_lookup(key: str):
    async with _store_lock:
        ent = _load_json(_IDEM_PATH, {}).get(key)
    if ent and time.time() - ent.get("ts", 0) < _IDEM_TTL:
        return ent
    return None


async def _idem_store(key: str, status: int, body: dict) -> None:
    async with _store_lock:
        store = _load_json(_IDEM_PATH, {})
        now = time.time()
        store = {k: v for k, v in store.items() if now - v.get("ts", 0) < _IDEM_TTL}
        store[key] = {"ts": now, "status": status, "body": body}
        if len(store) > _IDEM_MAX:
            for k in sorted(store, key=lambda k: store[k]["ts"])[: len(store) - _IDEM_MAX]:
                del store[k]
        _save_json(_IDEM_PATH, store)


async def _queue_add(kind: str, notebook_id: str, payload: dict) -> str:
    qid = uuid.uuid4().hex
    async with _store_lock:
        queue = _load_json(_QUEUE_PATH, [])
        queue.append({
            "id": qid, "kind": kind, "notebook_id": notebook_id,
            "payload": payload, "ts": time.time(), "attempts": 0,
        })
        _save_json(_QUEUE_PATH, queue)
    return qid


async def _queue_flush() -> dict:
    """Retry queued writes in FIFO order. Returns per-entry outcomes."""
    async with _store_lock:
        queue = _load_json(_QUEUE_PATH, [])
    if not queue:
        return {"flushed": 0, "remaining": 0, "results": []}

    results = []
    remaining = []
    client = await get_client()
    async with client:
        for ent in queue:
            try:
                if ent["kind"] == "text":
                    src = await client.sources.add_text(
                        ent["notebook_id"], ent["payload"]["title"], ent["payload"]["content"])
                elif ent["kind"] == "url":
                    src = await client.sources.add_url(
                        ent["notebook_id"], ent["payload"]["url"], wait=ent["payload"].get("wait", True))
                elif ent["kind"] == "youtube":
                    src = await client.sources.add_youtube(
                        ent["notebook_id"], ent["payload"]["url"], wait=ent["payload"].get("wait", True))
                else:
                    raise ValueError(f"unknown queue kind {ent['kind']}")
                results.append({"id": ent["id"], "ok": True})
            except Exception as e:
                ent["attempts"] = ent.get("attempts", 0) + 1
                ent["last_error"] = str(e)[:300]
                remaining.append(ent)
                results.append({"id": ent["id"], "ok": False, "error": str(e)[:200]})
                break  # auth likely down; stop hammering

    remaining += queue[len(results):]
    async with _store_lock:
        _save_json(_QUEUE_PATH, remaining)
    flushed = sum(1 for r in results if r["ok"])
    return {"flushed": flushed, "remaining": len(remaining), "results": results}


# ----------------------------
# Auth keepalive + health probe (subprocess to the bundled CLI)
# ----------------------------
def _cli_base() -> list[str]:
    cmd = [sys.executable, "-m", "notebooklm"]
    if AUTH_STORAGE_PATH:
        cmd += ["--storage", AUTH_STORAGE_PATH]
    return cmd


async def _run_cli(args: list[str], timeout: int = 120) -> dict:
    proc = await asyncio.create_subprocess_exec(
        *_cli_base() + args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"exit": -1, "error": f"timeout after {timeout}s"}
    result: dict[str, Any] = {"exit": proc.returncode}
    try:
        parsed = json.loads(out.decode() or "{}")
        if isinstance(parsed, dict):
            result.update(parsed)
        else:
            result["output"] = parsed
    except json.JSONDecodeError:
        if out.strip():
            result["stdout"] = out.decode()[-800:]
    if proc.returncode != 0 and err.strip():
        result["stderr"] = err.decode()[-800:]
    return result


async def _auth_probe() -> dict:
    """Passive read-only auth check: never refreshes or writes storage."""
    args = ["auth", "check", "--test", "--passive", "--json"]
    res = await _run_cli(args, timeout=60)
    healthy = res.get("exit") == 0
    return {
        "status": "ok" if healthy else "expired",
        "probe": res,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def _auth_refresh() -> dict:
    args = ["auth", "refresh", "--verify", "--json"]
    if HEADLESS_REAUTH:
        args.append("--allow-headless")
    res = await _run_cli(args, timeout=180)
    return {
        "ok": res.get("exit") == 0,
        "refresh": res,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }


async def _keepalive_loop(app: FastAPI) -> None:
    # First refresh shortly after startup, then on the configured cadence.
    await asyncio.sleep(10)
    while True:
        try:
            app.state.last_keepalive = await _auth_refresh()
            app.state.auth = await _auth_probe()
            if app.state.auth.get("status") == "ok":
                flushed = await _queue_flush()
                if flushed.get("flushed"):
                    app.state.last_queue_flush = flushed
        except Exception as e:  # keep the loop alive no matter what
            app.state.last_keepalive = {"ok": False, "error": str(e)[:300]}
        await asyncio.sleep(KEEPALIVE_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.auth = {"status": "unknown"}
    app.state.last_keepalive = None
    task = asyncio.create_task(_keepalive_loop(app)) if KEEPALIVE_INTERVAL > 0 else None
    yield
    if task:
        task.cancel()
    await _close_shared_client()


# ----------------------------
# Models
# ----------------------------
class NotebookCreateReq(BaseModel):
    title: str


class NotebookRenameReq(BaseModel):
    new_title: str


class SourceAddUrlReq(BaseModel):
    url: str
    wait: bool = True
    enqueue_on_failure: Optional[bool] = None  # default: NOTEBOOKLM_QUEUE_WRITES


class SourceAddTextReq(BaseModel):
    title: str
    content: str
    enqueue_on_failure: Optional[bool] = None


class SourceAddYoutubeReq(BaseModel):
    url: str
    wait: bool = True
    enqueue_on_failure: Optional[bool] = None


class SourcePruneReq(BaseModel):
    prefix: Optional[str] = None          # only consider sources whose title starts with this
    older_than_days: Optional[int] = None # only consider sources older than N days
    keep: int = 0                         # always keep the N newest matching sources
    include_errors: bool = True           # also delete sources with status=ERROR
    dry_run: bool = True                  # default safe: report only


class ChatAskReq(BaseModel):
    question: str


class ArtifactGenerateReq(BaseModel):
    type: Literal[
        "audio",
        "video",
        "report",
        "quiz",
        "flashcards",
        "slide_deck",
        "infographic",
        "data_table",
        "mind_map",
    ]
    options: Dict[str, Any] = {}


class TaskPollResp(BaseModel):
    ok: bool
    status: Any


# ----------------------------
# Helpers
# ----------------------------
def _dump(obj):
    return obj.model_dump() if hasattr(obj, "model_dump") else getattr(obj, "__dict__", obj)


async def _idem_replay(idem_key: Optional[str]):
    if not idem_key:
        return None
    hit = await _idem_lookup(idem_key)
    if hit:
        return JSONResponse(hit["body"], status_code=hit["status"],
                            headers={"X-Idempotent-Replay": "true"})
    return None


async def _maybe_enqueue(kind: str, notebook_id: str, payload: dict,
                         enqueue_flag: Optional[bool], exc_detail: str):
    """Queue a failed write if enabled. Returns a 202 response or re-raises."""
    if enqueue_flag if enqueue_flag is not None else QUEUE_WRITES_DEFAULT:
        qid = await _queue_add(kind, notebook_id, payload)
        return JSONResponse(
            {"ok": True, "queued": True, "queue_id": qid, "reason": exc_detail[:200]},
            status_code=202,
        )
    return None


# ----------------------------
# App
# ----------------------------
app = FastAPI(
    title="NotebookLM REST API (powered by notebooklm-py)",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)


@app.get("/health")
async def health():
    return {"ok": True, "auth": app.state.auth.get("status", "unknown")}


@app.get("/health/auth")
async def health_auth(request: Request):
    """Proactive auth probe. Cached for 60s; passive (read-only, no refresh)."""
    cached = app.state.auth or {}
    ts = cached.get("_ts", 0)
    if time.time() - ts > _HEALTH_CACHE_TTL:
        probe = await _auth_probe()
        probe["_ts"] = time.time()
        app.state.auth = probe
        cached = probe
    body = {
        "ok": cached.get("status") == "ok",
        "auth": cached.get("status"),
        "probe": cached.get("probe"),
        "checked_at": cached.get("checked_at"),
        "last_keepalive": app.state.last_keepalive,
        "keepalive_interval_s": KEEPALIVE_INTERVAL,
        "queued_writes": len(_load_json(_QUEUE_PATH, [])),
    }
    # Health monitors key on status code — 503 when auth is broken.
    return JSONResponse(body, status_code=200 if body["ok"] else 503)


@app.post("/health/auth/refresh")
async def health_auth_refresh():
    """Force an immediate auth refresh cycle (manual recovery)."""
    result = await _auth_refresh()
    app.state.last_keepalive = result
    app.state.auth = {"status": "unknown", "_ts": 0}  # bust probe cache
    return result


# ----------------------------
# Write queue management
# ----------------------------
@app.get("/v1/queue")
async def list_queue():
    return {"ok": True, "items": _load_json(_QUEUE_PATH, [])}


@app.post("/v1/queue/flush")
async def flush_queue():
    return {"ok": True, **(await _queue_flush())}


@app.delete("/v1/queue/{qid}")
async def delete_queued(qid: str):
    async with _store_lock:
        queue = _load_json(_QUEUE_PATH, [])
        new = [e for e in queue if e.get("id") != qid]
        _save_json(_QUEUE_PATH, new)
    return {"ok": True, "deleted": len(queue) - len(new)}


# ----------------------------
# Notebooks
# ----------------------------
@app.get("/v1/notebooks")
async def list_notebooks(request: Request):
    client = await get_client()
    async with client:
        try:
            nbs = await client.notebooks.list()
            scope = getattr(request.state, "key_scope", None)
            if scope:
                allowed = scope.get("notebooks", ["*"])
                if "*" not in allowed:
                    nbs = [nb for nb in nbs if nb.id in allowed]
            return {"ok": True, "items": [_dump(nb) for nb in nbs]}
        except RPCError as e:
            raise map_rpc_error(e)


@app.post("/v1/notebooks")
async def create_notebook(req: NotebookCreateReq,
                          idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    if (replay := await _idem_replay(idempotency_key)) is not None:
        return replay
    client = await get_client()
    async with client:
        try:
            nb = await client.notebooks.create(req.title)
            body = {"ok": True, "notebook": _dump(nb)}
            if idempotency_key:
                await _idem_store(idempotency_key, 200, body)
            return body
        except RPCError as e:
            raise map_rpc_error(e)


@app.get("/v1/notebooks/{notebook_id}")
async def get_notebook(notebook_id: str):
    client = await get_client()
    async with client:
        try:
            nb = await client.notebooks.get(notebook_id)
            return {"ok": True, "notebook": _dump(nb)}
        except RPCError as e:
            raise map_rpc_error(e)


@app.delete("/v1/notebooks/{notebook_id}")
async def delete_notebook(notebook_id: str):
    client = await get_client()
    async with client:
        try:
            ok = await client.notebooks.delete(notebook_id)
            return {"ok": True, "deleted": bool(ok)}
        except RPCError as e:
            raise map_rpc_error(e)


@app.patch("/v1/notebooks/{notebook_id}/rename")
async def rename_notebook(notebook_id: str, req: NotebookRenameReq):
    client = await get_client()
    async with client:
        try:
            nb = await client.notebooks.rename(notebook_id, req.new_title)
            return {"ok": True, "notebook": _dump(nb)}
        except RPCError as e:
            raise map_rpc_error(e)


@app.get("/v1/notebooks/{notebook_id}/summary")
async def get_notebook_summary(notebook_id: str):
    client = await get_client()
    async with client:
        try:
            summary = await client.notebooks.get_summary(notebook_id)
            return {"ok": True, "summary": summary}
        except RPCError as e:
            raise map_rpc_error(e)


@app.get("/v1/notebooks/{notebook_id}/description")
async def get_notebook_description(notebook_id: str):
    client = await get_client()
    async with client:
        try:
            desc = await client.notebooks.get_description(notebook_id)
            return {"ok": True, "description": _dump(desc)}
        except RPCError as e:
            raise map_rpc_error(e)


# ----------------------------
# Sources
# ----------------------------
@app.get("/v1/notebooks/{notebook_id}/sources")
async def list_sources(notebook_id: str):
    client = await get_client()
    async with client:
        try:
            items = await client.sources.list(notebook_id)
            return {"ok": True, "items": [_dump(s) for s in items]}
        except RPCError as e:
            raise map_rpc_error(e)


@app.post("/v1/notebooks/{notebook_id}/sources/url")
async def add_source_url(notebook_id: str, req: SourceAddUrlReq,
                         idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    if (replay := await _idem_replay(idempotency_key)) is not None:
        return replay
    client = await get_client()
    async with client:
        try:
            src = await client.sources.add_url(notebook_id, req.url, wait=req.wait)
        except TypeError:
            try:
                src = await client.sources.add_url(notebook_id, req.url)
            except RPCError as e:
                raise map_rpc_error(e)
        except RPCError as e:
            if (q := await _maybe_enqueue("url", notebook_id, req.model_dump(),
                                          req.enqueue_on_failure, str(e))) is not None:
                return q
            raise map_rpc_error(e)
    body = {"ok": True, "source": _dump(src)}
    if idempotency_key:
        await _idem_store(idempotency_key, 200, body)
    return body


@app.post("/v1/notebooks/{notebook_id}/sources/youtube")
async def add_source_youtube(notebook_id: str, req: SourceAddYoutubeReq,
                             idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    if (replay := await _idem_replay(idempotency_key)) is not None:
        return replay
    client = await get_client()
    async with client:
        try:
            src = await client.sources.add_youtube(notebook_id, req.url, wait=req.wait)
        except TypeError:
            try:
                src = await client.sources.add_youtube(notebook_id, req.url)
            except RPCError as e:
                raise map_rpc_error(e)
        except RPCError as e:
            if (q := await _maybe_enqueue("youtube", notebook_id, req.model_dump(),
                                          req.enqueue_on_failure, str(e))) is not None:
                return q
            raise map_rpc_error(e)
    body = {"ok": True, "source": _dump(src)}
    if idempotency_key:
        await _idem_store(idempotency_key, 200, body)
    return body


@app.post("/v1/notebooks/{notebook_id}/sources/text")
async def add_source_text(notebook_id: str, req: SourceAddTextReq,
                          idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    if (replay := await _idem_replay(idempotency_key)) is not None:
        return replay
    client = await get_client()
    async with client:
        try:
            src = await client.sources.add_text(notebook_id, req.title, req.content)
        except RPCError as e:
            if (q := await _maybe_enqueue("text", notebook_id, req.model_dump(),
                                          req.enqueue_on_failure, str(e))) is not None:
                return q
            raise map_rpc_error(e)
        except HTTPException:
            raise
        except Exception as e:
            # client init / unexpected failure: also queueable
            if (q := await _maybe_enqueue("text", notebook_id, req.model_dump(),
                                          req.enqueue_on_failure, str(e))) is not None:
                return q
            raise
    body = {"ok": True, "source": _dump(src)}
    if idempotency_key:
        await _idem_store(idempotency_key, 200, body)
    return body


@app.post("/v1/notebooks/{notebook_id}/sources/file")
async def add_source_file(
    notebook_id: str,
    upload: UploadFile = File(...),
    mime_type: Optional[str] = Form(None),
):
    suffix = os.path.splitext(upload.filename or "")[1] or ".bin"
    tmp_path = os.path.join(tempfile.gettempdir(), f"nb_{uuid.uuid4().hex}{suffix}")
    with open(tmp_path, "wb") as f:
        f.write(await upload.read())

    client = await get_client()
    async with client:
        try:
            src = await client.sources.add_file(notebook_id, tmp_path, mime_type=mime_type)
            return {"ok": True, "source": _dump(src)}
        except RPCError as e:
            raise map_rpc_error(e)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@app.post("/v1/notebooks/{notebook_id}/sources/prune")
async def prune_sources(notebook_id: str, req: SourcePruneReq):
    """Lifecycle: delete old/duplicate/error sources. Dry-run by default."""
    client = await get_client()
    async with client:
        try:
            items = await client.sources.list(notebook_id)
        except RPCError as e:
            raise map_rpc_error(e)

    now = datetime.now(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    candidates = []
    for s in items:
        if req.prefix and not (s.title or "").startswith(req.prefix):
            continue
        if req.older_than_days is not None:
            created = s.created_at or epoch
            if (now - created).days < req.older_than_days:
                continue
        if req.prefix or req.older_than_days is not None:
            candidates.append(s)

    candidates.sort(key=lambda s: s.created_at or epoch, reverse=True)
    to_delete = {s.id: s for s in candidates[req.keep:]}
    if req.include_errors:
        for s in items:
            if getattr(s, "is_error", False):
                to_delete.setdefault(s.id, s)

    if req.dry_run:
        return {
            "ok": True, "dry_run": True,
            "would_delete": [{"id": s.id, "title": s.title,
                              "created_at": str(s.created_at)} for s in to_delete.values()],
            "count": len(to_delete), "total_sources": len(items),
        }

    deleted, errors = [], []
    async with client:
        for s in to_delete.values():
            try:
                await client.sources.delete(notebook_id, s.id)
                deleted.append(s.id)
            except RPCError as e:
                errors.append({"id": s.id, "error": str(e)[:200]})
    return {"ok": True, "deleted": deleted, "count": len(deleted),
            "errors": errors, "total_sources": len(items)}


@app.get("/v1/notebooks/{notebook_id}/sources/{source_id}/fulltext")
async def get_source_fulltext(notebook_id: str, source_id: str):
    client = await get_client()
    async with client:
        try:
            ft = await client.sources.get_fulltext(notebook_id, source_id)
            return {"ok": True, "fulltext": _dump(ft)}
        except RPCError as e:
            raise map_rpc_error(e)


@app.get("/v1/notebooks/{notebook_id}/sources/{source_id}/guide")
async def get_source_guide(notebook_id: str, source_id: str):
    client = await get_client()
    async with client:
        try:
            guide = await client.sources.get_guide(notebook_id, source_id)
            return {"ok": True, "guide": guide}
        except RPCError as e:
            raise map_rpc_error(e)


@app.delete("/v1/notebooks/{notebook_id}/sources/{source_id}")
async def delete_source(notebook_id: str, source_id: str):
    client = await get_client()
    async with client:
        try:
            await client.sources.delete(notebook_id, source_id)
            return {"ok": True, "deleted": True}
        except RPCError as e:
            raise map_rpc_error(e)


# ----------------------------
# Chat
# ----------------------------
@app.post("/v1/notebooks/{notebook_id}/chat/ask")
async def chat_ask(notebook_id: str, req: ChatAskReq):
    client = await get_client()
    async with client:
        try:
            result = await client.chat.ask(notebook_id, req.question)
            if hasattr(result, "model_dump"):
                return {"ok": True, "result": result.model_dump()}
            return {"ok": True, "result": getattr(result, "__dict__", {"answer": getattr(result, "answer", None)})}
        except RPCError as e:
            raise map_rpc_error(e)


# ----------------------------
# Artifacts: list / generate / poll / download
# ----------------------------
@app.get("/v1/notebooks/{notebook_id}/artifacts")
async def list_artifacts(notebook_id: str, type: Optional[str] = None):
    client = await get_client()
    async with client:
        try:
            items = await client.artifacts.list(notebook_id, type=type) if type else await client.artifacts.list(notebook_id)
            return {"ok": True, "items": [_dump(a) for a in items]}
        except RPCError as e:
            raise map_rpc_error(e)


@app.post("/v1/notebooks/{notebook_id}/artifacts/generate")
async def generate_artifact(notebook_id: str, req: ArtifactGenerateReq):
    client = await get_client()
    async with client:
        try:
            t = req.type
            opts = req.options or {}

            if t == "audio":
                status = await client.artifacts.generate_audio(notebook_id, **opts)
            elif t == "video":
                status = await client.artifacts.generate_video(notebook_id, **opts)
            elif t == "report":
                status = await client.artifacts.generate_report(notebook_id, **opts)
            elif t == "quiz":
                status = await client.artifacts.generate_quiz(notebook_id, **opts)
            elif t == "flashcards":
                status = await client.artifacts.generate_flashcards(notebook_id, **opts)
            elif t == "slide_deck":
                status = await client.artifacts.generate_slide_deck(notebook_id, **opts)
            elif t == "infographic":
                status = await client.artifacts.generate_infographic(notebook_id, **opts)
            elif t == "data_table":
                status = await client.artifacts.generate_data_table(notebook_id, **opts)
            elif t == "mind_map":
                out = await client.artifacts.generate_mind_map(notebook_id, **opts)
                return {"ok": True, "type": t, "result": out}
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported artifact type: {t}")

            payload = _dump(status)
            return {"ok": True, "type": t, "status": payload}
        except RPCError as e:
            raise map_rpc_error(e)


@app.get("/v1/notebooks/{notebook_id}/artifacts/tasks/{task_id}")
async def poll_task(notebook_id: str, task_id: str, wait: bool = False):
    client = await get_client()
    async with client:
        try:
            if wait:
                status = await client.artifacts.wait_for_completion(notebook_id, task_id)
            else:
                status = await client.artifacts.poll_status(notebook_id, task_id)

            payload = _dump(status)
            return {"ok": True, "status": payload}
        except RPCError as e:
            raise map_rpc_error(e)


@app.get("/v1/notebooks/{notebook_id}/artifacts/download")
async def download_artifact(
    notebook_id: str,
    type: Literal[
        "audio",
        "video",
        "infographic",
        "slide_deck",
        "report",
        "mind_map",
        "data_table",
        "quiz",
        "flashcards",
    ],
    artifact_id: Optional[str] = None,
    output_format: Optional[Literal["json", "markdown", "html"]] = None,
):
    suffix_map = {
        "audio": ".mp4",
        "video": ".mp4",
        "infographic": ".png",
        "slide_deck": ".pdf",
        "report": ".md",
        "mind_map": ".json",
        "data_table": ".csv",
        "quiz": ".json" if (output_format in (None, "json")) else (".md" if output_format == "markdown" else ".html"),
        "flashcards": ".json" if (output_format in (None, "json")) else (".md" if output_format == "markdown" else ".html"),
    }
    out_path = os.path.join(tempfile.gettempdir(), f"nlm_{uuid.uuid4().hex}{suffix_map[type]}")

    client = await get_client()
    async with client:
        try:
            if type == "audio":
                await client.artifacts.download_audio(notebook_id, out_path, artifact_id=artifact_id)
            elif type == "video":
                await client.artifacts.download_video(notebook_id, out_path, artifact_id=artifact_id)
            elif type == "infographic":
                await client.artifacts.download_infographic(notebook_id, out_path, artifact_id=artifact_id)
            elif type == "slide_deck":
                await client.artifacts.download_slide_deck(notebook_id, out_path, artifact_id=artifact_id)
            elif type == "report":
                await client.artifacts.download_report(notebook_id, out_path, artifact_id=artifact_id)
            elif type == "mind_map":
                await client.artifacts.download_mind_map(notebook_id, out_path, artifact_id=artifact_id)
            elif type == "data_table":
                await client.artifacts.download_data_table(notebook_id, out_path, artifact_id=artifact_id)
            elif type == "quiz":
                await client.artifacts.download_quiz(
                    notebook_id, out_path, artifact_id=artifact_id, output_format=(output_format or "json")
                )
            elif type == "flashcards":
                await client.artifacts.download_flashcards(
                    notebook_id, out_path, artifact_id=artifact_id, output_format=(output_format or "json")
                )
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported type: {type}")

            filename = os.path.basename(out_path)
            return FileResponse(out_path, filename=filename)
        except RPCError as e:
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except OSError:
                pass
            raise map_rpc_error(e)
