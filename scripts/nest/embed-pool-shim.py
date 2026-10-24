#!/usr/bin/env python3
"""embed-pool-shim — ollama-shaped /api/embed racing proxy (MEM-0805).

mddb embeds only through its configured EMBEDDING_API_URL; there is no
vector-ingest endpoint, so the only way to pool the fleet's embed capacity
is to front it with something that speaks the ollama HTTP API. This shim
accepts an ollama request and fans it out to every upstream in the pool
concurrently — the FIRST successful response wins (hedged requests; kills
tail latency on slow/loaded CPU boxes, the failure mode that 400'd bench
queries on a saturated idc03).

Config (env):
  EMBED_POOL_UPSTREAMS  comma list, e.g. http://idc03:11434,http://idc02:11434
  EMBED_POOL_ADDR       listen addr           (default 127.0.0.1:11436)
  EMBED_POOL_TIMEOUT_S  per-upstream timeout  (default 8 — must stay under
                        mddb's internal embed deadline ~10s)

Endpoints:
  POST /api/embed            raced across all upstreams, first 200 wins
  *    (anything else)       proxied to the first upstream that answers —
                             keeps /api/tags, /api/ps, /api/version healthy
  GET  /health               pool status + per-upstream win/fail stats
"""
import json
import os
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAMS = [u.strip().rstrip("/") for u in
             os.environ.get("EMBED_POOL_UPSTREAMS", "").split(",") if u.strip()]
ADDR = os.environ.get("EMBED_POOL_ADDR", "127.0.0.1:11436")
TIMEOUT = float(os.environ.get("EMBED_POOL_TIMEOUT_S", "8"))
RACED = {"/api/embed", "/api/embeddings"}

_stats = {u: {"wins": 0, "fails": 0, "last_ms": 0} for u in UPSTREAMS}
_lock = threading.Lock()


def _call(upstream, path, body):
    req = urllib.request.Request(
        upstream + path, data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = urllib.request.urlopen(req, timeout=TIMEOUT)
    data = r.read()
    return r.status, data, (time.time() - t0) * 1000


def _race(path, body):
    """Fan out to all upstreams; return the first 2xx result."""
    q = []

    def worker(u):
        try:
            st, data, ms = _call(u, path, body)
            if 200 <= st < 300:
                with _lock:
                    _stats[u]["wins"] += 1
                    _stats[u]["last_ms"] = int(ms)
                q.append((u, st, data))
            else:
                with _lock:
                    _stats[u]["fails"] += 1
        except Exception:
            with _lock:
                _stats[u]["fails"] += 1

    ts = [threading.Thread(target=worker, args=(u,), daemon=True)
          for u in UPSTREAMS]
    for t in ts:
        t.start()
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if q:
            return q[0]
        time.sleep(0.02)
    for t in ts:
        t.join(timeout=0.1)
    return (None, 504, b'{"error":"no upstream answered in time"}')


def _first(path, body):
    """Non-raced proxy: try each upstream in order until one answers."""
    for u in UPSTREAMS:
        try:
            st, data, _ = _call(u, path, body)
            if 200 <= st < 400:
                return u, st, data
        except Exception:
            continue
    return (None, 502, b'{"error":"no upstream available"}')


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            with _lock:
                st = {u: dict(s) for u, s in _stats.items()}
            return self._send(200, json.dumps(
                {"ok": True, "upstreams": UPSTREAMS,
                 "timeout_s": TIMEOUT, "stats": st}).encode())
        # pass-through GETs (e.g. /api/tags, /api/ps, /api/version)
        _, st, data = _first(self.path, None)
        self._send(st, data)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path in RACED:
            _, st, data = _race(self.path, body)
        else:
            _, st, data = _first(self.path, body)
        self._send(st, data)


def main():
    if not UPSTREAMS:
        raise SystemExit("EMBED_POOL_UPSTREAMS is empty — "
                         "set a comma list of ollama base URLs")
    host, port = ADDR.rsplit(":", 1)
    srv = ThreadingHTTPServer((host, int(port)), H)
    print(f"embed-pool-shim on {ADDR} racing {len(UPSTREAMS)} upstreams, "
          f"timeout {TIMEOUT}s")
    srv.serve_forever()


if __name__ == "__main__":
    main()
