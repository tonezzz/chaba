"""MEM-1507: MDDB publisher readiness gate + bounded write retries.

Both publishers used to POST straight to /v1/add after only a TCP/health
probe. After an OOM restart mddb opens /health ~84-104s before /v1 routes are
live, so the write got a 404 and the timer tick exited 1. These tests prove
that both scripts now (a) gate on GET /v1/stats, (b) retry only transient
failures at most 3 times, and (c) refuse the POST when routes never appear.

Runs under the system python; httpx is stubbed and the ops script's
import-time health probes are excluded by AST filtering.

    python3 -m pytest tests/test_publisher_mddb_retry.py -q
"""
import ast
import http.client
import io
import os
import sys
import types
import urllib.error
from pathlib import Path

import pytest

# The ops script imports backend.mddb_client, which imports httpx. Only
# is_cms_collection() is used here; stub httpx when running under the system
# python (the commit hook) so this test needs no venv.
try:
    import httpx  # noqa: F401
except ImportError:
    sys.modules.setdefault("httpx", types.ModuleType("httpx"))

REPO = Path(__file__).resolve().parents[1]
ADA_VOICE = Path(os.environ.get(
    "ADA_VOICE_ROOT", REPO.parent / "ada-voice"))

MEDIA_SCRIPT = REPO / "scripts/ada/media-inbox-update.py"
OPS_SCRIPT = ADA_VOICE / "scripts/ops-health-report.py"


class Clock:
    """Deterministic time source for the module under test."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Resp:
    status = 200

    def __init__(self, body=b'{"ok": true}'):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def err(code):
    return urllib.error.HTTPError(
        "http://x/v1/add", code, "err", {}, io.BytesIO(b"{}"))


def url_of(req):
    return getattr(req, "full_url", None) or str(req)


class Module:
    pass


def load(path, definitions_only=False):
    """Exec a script's definitions without its import-time side effects.

    ops-health-report.py probes the fleet and publishes at import time. Keep
    only imports, uppercase constants and function defs so its post() can be
    tested offline without network calls.
    """
    source = path.read_text()
    if definitions_only:
        keep = []
        for node in ast.parse(source).body:
            if isinstance(node, (ast.Import, ast.ImportFrom,
                                 ast.FunctionDef, ast.ClassDef)):
                keep.append(node)
            elif isinstance(node, ast.Assign) and all(
                    isinstance(t, ast.Name) and t.id.isupper()
                    for t in node.targets):
                keep.append(node)
        source = ast.unparse(ast.Module(body=keep, type_ignores=[]))
        # The original script inserts its repo root on sys.path with an
        # expression statement; re-add that before compiling the subset.
        source = ("import sys\n"
                  f"sys.path.insert(0, {str(path.resolve().parent.parent)!r})\n"
                  + source)
    mod = Module()
    vars(mod)["__file__"] = str(path)
    vars(mod)["__name__"] = path.stem
    exec(compile(source, str(path), "exec"), vars(mod))
    mod.ROUTE_WAIT_S = 12
    mod.WRITE_TIMEOUT = 2
    mod.time = Clock()
    return mod


def harness(mod, which):
    """Wire a scripted urlopen into the module and return (post, calls, seq)."""
    calls = []
    seq = []

    def fake(req, timeout=None):
        calls.append((url_of(req), timeout))
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    mod.urllib.request.urlopen = fake
    payload = ({"collection": "x", "key": "k", "contentMd": "x", "meta": {}}
               if which == "media" else {"collection": "x", "key": "k"})
    if which == "media":
        post = lambda: mod._post("add", payload)  # noqa: E731
    else:
        post = lambda: mod.post("/add", payload)  # noqa: E731
    return post, calls, seq


def pair():
    out = []
    if MEDIA_SCRIPT.exists():
        out.append(("media", load(MEDIA_SCRIPT)))
    if OPS_SCRIPT.exists():
        # The script's own sys.path insertion is an executable statement that
        # AST filtering drops, so provide its repo root here.
        sys.path.insert(0, str(ADA_VOICE))
        out.append(("ops", load(OPS_SCRIPT, definitions_only=True)))
    return out


# Load each script once at collection; re-importing the ops backend is slow.
PAIRS = pair()
IDS = [name for name, _mod in PAIRS]


@pytest.mark.parametrize("which,mod", PAIRS, ids=IDS)
def test_readiness_404_then_503_then_post(which, mod):
    post, calls, seq = harness(mod, which)
    seq.extend([err(404), err(503), Resp(), Resp()])
    assert post() == {"ok": True}
    assert len(calls) == 4
    assert "/stats" in calls[0][0]
    assert "/add" in calls[-1][0]
    assert calls[-1][1] == 2


# Load each script once at collection; re-importing the ops backend is slow.
PAIRS = pair()
IDS = [name for name, _mod in PAIRS]


@pytest.mark.parametrize("which,mod", PAIRS, ids=IDS)
def test_transient_disconnect_is_retried(which, mod):
    post, calls, seq = harness(mod, which)
    seq.extend([Resp(), http.client.RemoteDisconnected(), Resp()])
    assert post() == {"ok": True}
    assert len(calls) == 3
    assert all("/add" in c[0] for c in calls[1:])


# Load each script once at collection; re-importing the ops backend is slow.
PAIRS = pair()
IDS = [name for name, _mod in PAIRS]


@pytest.mark.parametrize("which,mod", PAIRS, ids=IDS)
def test_retryable_errors_are_bounded_at_three(which, mod):
    post, calls, seq = harness(mod, which)
    seq.extend([Resp(), err(404), err(404), err(404)])
    with pytest.raises(urllib.error.HTTPError):
        post()
    assert len(calls) == 4  # one readiness probe + three POST attempts


# Load each script once at collection; re-importing the ops backend is slow.
PAIRS = pair()
IDS = [name for name, _mod in PAIRS]


@pytest.mark.parametrize("which,mod", PAIRS, ids=IDS)
def test_routes_never_ready_refuses_post(which, mod):
    post, calls, seq = harness(mod, which)
    mod.time = Clock()
    seq.extend([err(404)] * 40)
    with pytest.raises(RuntimeError, match="not ready"):
        post()
    assert calls and all("/stats" in c[0] for c in calls)
    assert mod.time.now >= 12


# Load each script once at collection; re-importing the ops backend is slow.
PAIRS = pair()
IDS = [name for name, _mod in PAIRS]


@pytest.mark.parametrize("which,mod", PAIRS, ids=IDS)
def test_non_retryable_error_fails_immediately(which, mod):
    post, calls, seq = harness(mod, which)
    seq.extend([Resp(), err(400)])
    with pytest.raises(urllib.error.HTTPError) as exc:
        post()
    assert exc.value.code == 400
    assert len(calls) == 2
