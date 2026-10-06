#!/usr/bin/env python3
"""report-api — on-demand trigger + status for the chaba report chain.

  GET  /health  -> {"ok": true}
  GET  /status  -> {"running": bool, "generated_at": str|null}
  POST /refresh -> start chaba-system-report.service (L1 host audits ->
                   L2 fleet rollup -> L3 system report — refreshing the
                   top level refreshes every linked layer). 409 while a
                   run is in flight.

Write gate mirrors board-api: POSTs need a verified tailnet identity
(Tailscale-User-Login, injected by tailscale serve and re-checked here
against the client IP chain) or a direct loopback caller. Caddy also
denies anonymous writes at the edge (stacks/web/Caddyfile).
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from pathlib import Path

# Reuse board-api's write gate (hyphenated filename — load by path so the
# tailnet-identity check stays single-sourced).
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "board_api", Path(__file__).resolve().parent.parent / "board" / "board-api.py")
_board_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_board_api)
caller_identity = _board_api.caller_identity

REPO = Path(__file__).resolve().parent.parent.parent
SUMMARY_YML = REPO / "stacks/web/public/apps/system-report/data/system-report.yml"
SERVICE = "chaba-system-report.service"
PORT = int(os.environ.get("REPORT_API_PORT", "8792"))
BIND = os.environ.get("REPORT_API_BIND", "127.0.0.1")
# Service-to-service auth (Ada, automation): bearer token alongside the
# tailnet-identity gate. Empty = disabled.
TOKEN = os.environ.get("REPORT_API_TOKEN", "")
# Completion notice — POST a report-updated doc into Ada's ops events
# collection so she can surface it on the next turn (design §5).
EVENTS_URL = os.environ.get(
    "REPORT_EVENTS_URL", "http://100.102.134.91:11023/v1").rstrip("/")
EVENTS_COLLECTION = os.environ.get(
    "REPORT_EVENTS_COLLECTION", "ada-ha-events-tony")
RUN_NODE = REPO / "scripts/report/run-node.py"
sys.path.insert(0, str(REPO / "scripts" / "lib"))
import report as reportlib  # noqa: E402

_GRAPH_LOCK = threading.Lock()  # one walk at a time — requests coalesce
_GRAPH_LAST: dict = {}          # last walk result for /status


def _subtree(nodes: dict, root: str) -> dict:
    """root + every node it consumes (transitive children)."""
    out, stack = {}, [root]
    while stack:
        nid = stack.pop()
        if nid in out or nid not in nodes:
            continue
        out[nid] = nodes[nid]
        stack.extend(nodes[nid].get("children") or [])
    return out


def _ancestors(nodes: dict, root: str) -> set:
    """depth=full sideways fan-out: nodes that consume root (and so on
    up), so a leaf refresh reaches every report built on it."""
    parents = {}
    for n in nodes.values():
        for c in n.get("children") or []:
            parents.setdefault(c, set()).add(n["id"])
    out, stack = set(), [root]
    while stack:
        nid = stack.pop()
        for p in parents.get(nid, ()):
            if p not in out:
                out.add(p)
                stack.append(p)
    return out


def _depth_of(nodes: dict, nid: str, memo: dict) -> int:
    """Leaves-first ordering: 0 = no children."""
    if nid in memo:
        return memo[nid]
    kids = [c for c in (nodes.get(nid) or {}).get("children") or []
            if c in nodes]
    memo[nid] = 1 + max((_depth_of(nodes, c, memo) for c in kids),
                        default=-1)
    return memo[nid]


def _run_node(nid: str) -> dict:
    proc = subprocess.run(
        ["/usr/bin/python3", str(RUN_NODE), nid],
        capture_output=True, text=True, timeout=1200)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"node": nid, "rc": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-400:]}


def _walk(root: str, depth: str, by: str) -> dict:
    """Dirty-driven walk: mark the requested node pending, then run
    leaves whose inputs are clean; parents go dirty as children land
    fresher than their inputs_at, and run once all inputs are fresh.
    Failure isolation: an un-runnable/failed child doesn't block the
    parent — it renders last-known-good with a delta."""
    reg = reportlib.load_registry()
    nodes = {n["id"]: n for n in reg.get("nodes") or []}
    if root not in nodes:
        return {"error": f"unknown node {root}"}
    target = _subtree(nodes, root)
    if depth == "leaf":
        target = {root: nodes[root]}
    elif depth == "full":
        target.update({a: nodes[a] for a in _ancestors(nodes, root)
                       if a in nodes})

    reportlib.pending_add(target[root]["meta"], by=by,
                          reason="user-refresh", depth=depth)
    if depth == "full":  # sideways: linked reports get their own mark
        for nid in _ancestors(nodes, root):
            reportlib.pending_add(nodes[nid]["meta"], by=by,
                                  reason="linked", depth=depth)

    order = sorted(target, key=lambda n: _depth_of(target, n, {}))
    ran, attempted, passes = {}, set(), 0
    max_passes = len(target) + 2
    while passes < max_passes:
        passes += 1
        progressed = False
        for nid in order:
            node = target[nid]
            if nid in ran:
                continue
            dirty, why = reportlib.node_dirty(node, reg)
            if not dirty:
                continue
            # Blocking children: dirty AND runnable AND not yet tried.
            # A failed or non-runnable child can't block — parents render
            # last-known-good with the delta (design §6).
            blocking = [
                c for c in node.get("children") or [] if c in target
                and c not in attempted
                and reportlib.node_dirty(target[c], reg)[0]
                and reportlib.generator_argv(target[c].get("generator"))]
            if blocking:
                continue
            if reportlib.generator_argv(node.get("generator")) is None:
                attempted.add(nid)  # non-runnable: satisfied by definition
                ran[nid] = {"node": nid, "skipped": "not runnable"}
            else:
                ran[nid] = _run_node(nid)
                attempted.add(nid)
            progressed = True
        if root in ran or not progressed:
            break
    # root blocked by dead children — run it anyway with last-known inputs
    if root not in ran and reportlib.generator_argv(
            target[root].get("generator")):
        ran[root] = _run_node(root)
    result = {"root": root, "depth": depth, "passes": passes, "ran": ran}
    _emit_event(root, depth, ran, by)
    return result


def _emit_event(root: str, depth: str, ran: dict, by: str) -> None:
    """report-updated doc into ada-ha-events-* — Ada reads ops events on
    her next turn ('the refresh you asked for landed, X changed')."""
    ok = [k for k, v in ran.items() if v.get("rc") == 0]
    bad = [k for k, v in ran.items() if v.get("rc") not in (0, None)]
    skipped = [k for k, v in ran.items() if v.get("skipped")]
    body = (f"report refresh ({depth}) by {by}: "
            f"{len(ok)} nodes regenerated"
            + (f", failed: {', '.join(bad)}" if bad else "")
            + (f", skipped: {', '.join(skipped)}" if skipped else ""))
    payload = {"collection": EVENTS_COLLECTION,
               "key": f"report-updated-{root}-"
                      f"{reportlib.now_iso().replace(':', '')}",
               "lang": "en",
               "contentMd": f"## Report updated\n\n{body}\n",
               "meta": {"kind": ["report-updated"], "node": [root],
                        "by": [by]}}
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{EVENTS_URL}/add",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        sys.stderr.write(f"report-api event emit failed: {exc}\n")


def _running() -> bool:
    return subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", SERVICE],
        check=False).returncode == 0


def _generated_at() -> str | None:
    try:
        import yaml
        doc = yaml.safe_load(SUMMARY_YML.read_text())
        return str((doc or {}).get("generated_at") or "") or None
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "report-api/1"

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True})
        elif self.path == "/status":
            self._json(200, {"running": _running() or _GRAPH_LAST.get(
                                 "state") == "running",
                             "generated_at": _generated_at(),
                             "graph": _GRAPH_LAST or None})
        elif self.path == "/pending":
            reg = reportlib.load_registry()
            self._json(200, {"pending": {
                n["id"]: (reportlib.load_meta(n.get("meta"))
                          .get("pending") or [])
                for n in reg.get("nodes") or []
                if reportlib.load_meta(n.get("meta")).get("pending")}})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/refresh":
            self._json(404, {"error": "not found"})
            return
        auth = self.headers.get("Authorization", "")
        if TOKEN and auth == f"Bearer {TOKEN}":
            who = "svc-token"  # service caller (Ada, automation)
        else:
            who = caller_identity(self.headers, self.client_address[0])
        if not who:
            self._json(403, {"error": "writes need a tailnet identity"})
            return
        body = {}
        if self.headers.get("Content-Length"):
            try:
                body = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"])))
            except Exception:
                self._json(400, {"error": "bad json"})
                return
        node, depth = body.get("node"), body.get("depth", "subtree")
        if node:
            # Graph refresh: mark pending, walk dirty inputs leaves-first,
            # re-render ancestors as their inputs land (design:
            # docs/design/report-live-refresh.md). One walk at a time.
            if depth not in ("leaf", "subtree", "full"):
                self._json(400, {"error": "depth must be leaf|subtree|full"})
                return
            if _GRAPH_LOCK.locked():
                self._json(409, {"ok": False, "running": True})
                return

            def _go():
                with _GRAPH_LOCK:
                    _GRAPH_LAST.clear()
                    _GRAPH_LAST.update({"state": "running", "root": node})
                    try:
                        _GRAPH_LAST.update(
                            _walk(node, depth, by=who))
                        _GRAPH_LAST["state"] = "done"
                    except Exception as exc:
                        _GRAPH_LAST.update({"state": "error",
                                            "error": str(exc)})
            threading.Thread(target=_go, daemon=True).start()
            self._json(202, {"ok": True, "node": node, "depth": depth,
                             "started_by": who})
            return
        # legacy: no body -> the whole L1->L3 oneshot
        if _running():
            self._json(409, {"ok": False, "running": True,
                             "generated_at": _generated_at()})
            return
        proc = subprocess.run(
            ["systemctl", "--user", "start", SERVICE],
            check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            self._json(500, {"ok": False,
                             "error": proc.stderr.strip() or "start failed"})
            return
        self._json(202, {"ok": True, "started_by": who})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("report-api %s\n" % (fmt % args))


if __name__ == "__main__":
    import unittest
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        sys.exit(unittest.main(argv=[sys.argv[0]]))
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
