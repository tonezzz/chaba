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
  EMBED_POOL_DEFER_UPSTREAMS  comma list of deferred-tier upstreams —
                        join the /api/embed race only after
                        EMBED_POOL_DEFER_AFTER_MS (default 1500) with no
                        primary winner; for opportunistic workers like
                        browser/WebGPU nest workers behind
                        embed-nest-bridge. Also tried last by pass-
                        through GETs/POSTs.
  EMBED_POOL_ADDR       listen addr           (default 127.0.0.1:11436)
  EMBED_POOL_TIMEOUT_S  per-upstream timeout  (default 8 — must stay under
                        mddb's internal embed deadline ~10s)
  EMBED_POOL_DEAD_AFTER       consecutive failures before an upstream is
                        parked                          (default 3)
  EMBED_POOL_DEAD_COOLDOWN_S  park duration; half-open retry after
                                                          (default 60)
  EMBED_POOL_LANE       optional lane marker forwarded to upstreams as the
                        `x-embed-lane` header — set "bulk" on pool serving
                        backfill banks so gemini-ollama-proxy budgets can
                        protect the free lane (card
                        embed-free-lane-daily-budget). A caller-set
                        x-embed-lane header always wins.

Endpoints:
  POST /api/embed            raced across all upstreams, first 200 wins
  *    (anything else)       proxied to the first upstream that answers —
                             keeps /api/tags, /api/ps, /api/version healthy
  GET  /health               pool status + per-upstream win/fail stats
"""
import http.client
import json
import os
import socket
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAMS = [u.strip().rstrip("/") for u in
             os.environ.get("EMBED_POOL_UPSTREAMS", "").split(",") if u.strip()]
# Deferred tier (MEM-0805 lane B): upstreams that join the /api/embed race
# only after DEFER_AFTER_MS with no primary winner — browser/nest workers
# (e.g. the iPhone WebGPU page via embed-nest-bridge) burn phone cycles
# only when the fleet can't answer fast.
DEFER_UPSTREAMS = [u.strip().rstrip("/") for u in
                   os.environ.get("EMBED_POOL_DEFER_UPSTREAMS", "")
                   .split(",") if u.strip()]
DEFER_AFTER_S = float(os.environ.get("EMBED_POOL_DEFER_AFTER_MS", "1500")) / 1000
ADDR = os.environ.get("EMBED_POOL_ADDR", "127.0.0.1:11436")
TIMEOUT = float(os.environ.get("EMBED_POOL_TIMEOUT_S", "8"))
RACED = {"/api/embed", "/api/embeddings"}
DEAD_AFTER = int(os.environ.get("EMBED_POOL_DEAD_AFTER", "3"))
DEAD_COOLDOWN_S = float(os.environ.get("EMBED_POOL_DEAD_COOLDOWN_S", "60"))
# Optional lane marker stamped on upstream calls (gemini-ollama-proxy
# budgets bulk lanes; ollama upstreams ignore the header).
LANE = os.environ.get("EMBED_POOL_LANE", "").strip() or None

_stats = {u: {"wins": 0, "fails": 0, "last_ms": 0, "consec": 0,
              "dead_until": 0.0} for u in UPSTREAMS + DEFER_UPSTREAMS}
_lock = threading.Lock()


def _alive(urls):
    """Upstreams not currently in dead cooldown; all if all are dead."""
    now = time.time()
    with _lock:
        live = [u for u in urls if _stats[u]["dead_until"] <= now]
    return live or list(urls)


def _alive_upstreams():
    return _alive(UPSTREAMS)


def _alive_deferred():
    return _alive(DEFER_UPSTREAMS)


def _record(u, ok):
    with _lock:
        st = _stats[u]
        if ok:
            st["wins"] += 1
            st["consec"] = 0
            st["dead_until"] = 0.0
        else:
            st["fails"] += 1
            st["consec"] += 1
            if st["consec"] >= DEAD_AFTER:
                st["dead_until"] = time.time() + DEAD_COOLDOWN_S


def _call(upstream, path, body, lane=None, stop=None, sockets=None):
    """Call one upstream. In race mode, register the raw socket at connect
    time so the winner can shut it down immediately. ollama computes the
    whole embedding BEFORE sending response headers, so a losing thread is
    blocked in getresponse() with no response object to close. Shutting
    down its socket from another thread (a) unblocks the blocked read and
    (b) makes ollama cancel its in-flight task — visible as "stop: cancel
    task" in its log — freeing CPU. Without this, every loser burns the
    full TIMEOUT (~8s) on a response nobody uses, which saturated capped
    con01's bge-m3 and logged a 400 for each wasted call.

    Returns (status, data, ms, sock) on success, or None if cancelled.
    `sock` is the identity token the winner uses to skip our own socket."""
    headers = {"Content-Type": "application/json"}
    if lane:
        headers["x-embed-lane"] = lane
    u = urllib.parse.urlsplit(upstream)
    t0 = time.time()
    conn = http.client.HTTPConnection(u.hostname, u.port or 80,
                                      timeout=TIMEOUT)
    conn.connect()
    sock = conn.sock
    if sockets is not None:
        with _lock:
            sockets.append((sock, conn))
    try:
        # A winner may have been declared between connect() and here.
        if stop is not None and stop.is_set():
            return None
        conn.request("POST", path, body=body, headers=headers)
        if stop is not None and stop.is_set():
            return None
        r = conn.getresponse()
        data = r.read()
        return r.status, data, (time.time() - t0) * 1000, sock
    finally:
        if sockets is not None:
            with _lock:
                try:
                    sockets.remove((sock, conn))
                except ValueError:
                    pass
        try:
            conn.close()
        except Exception:
            pass


def _abort_inflight(winner_sock, sockets):
    """Shut down every socket in flight except the winner's own."""
    if not sockets:
        return
    with _lock:
        for sock, _conn in sockets:
            if sock is winner_sock:
                continue
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass


def _race(path, body, lane=None):
    """Fan out to primary upstreams; deferred upstreams join the race
    only after DEFER_AFTER_S with no winner yet. First 2xx wins. Losing
    calls are cancelled immediately, not left to run into the timeout."""
    q = []
    threads = []
    sockets = []              # (socket, conn) registered at connect time
    stop = threading.Event()  # set by the winner to abort the other calls
    defer_fired = [False]
    t0 = time.time()

    def worker(u):
        try:
            result = _call(u, path, body, lane, stop, sockets)
            if result is None:       # cancelled before we sent the request
                return
            st, data, ms, sock = result
            if stop.is_set():        # another upstream already won
                return
            if 200 <= st < 300:
                _record(u, True)
                with _lock:
                    _stats[u]["last_ms"] = int(ms)
                stop.set()
                # Cancel the losers NOW, not at the 8s timeout. Their
                # exceptions are ignored because stop is set, so a lost
                # race is not recorded as an upstream failure (that bug
                # kept con01 in permanent dead-cooldown).
                _abort_inflight(sock, sockets)
                q.append((u, st, data))
            else:
                _record(u, False)
        except Exception:
            if not stop.is_set():    # ignore cancellation-driven exceptions
                _record(u, False)

    def spawn(u):
        t = threading.Thread(target=worker, args=(u,), daemon=True)
        t.start()
        threads.append(t)

    for u in _alive(UPSTREAMS):
        spawn(u)
    deadline = t0 + TIMEOUT
    while time.time() < deadline:
        if q:
            return q[0]
        if (DEFER_UPSTREAMS and not defer_fired[0]
                and time.time() - t0 >= DEFER_AFTER_S):
            defer_fired[0] = True
            for u in _alive_deferred():
                spawn(u)
        time.sleep(0.02)
    # No winner: abort everything still in flight before returning 504.
    stop.set()
    _abort_inflight(None, sockets)
    for t in threads:
        t.join(timeout=0.1)
    return (None, 504, b'{"error":"no upstream answered in time"}')


def _first(path, body, lane=None):
    """Non-raced proxy: try each upstream in order (primaries, then
    deferred) until one answers."""
    for u in _alive_upstreams() + _alive_deferred():
        try:
            st, data, _, _ = _call(u, path, body, lane)
            if 200 <= st < 400:
                _record(u, True)
                return u, st, data
            _record(u, False)
        except Exception:
            _record(u, False)
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

    def _lane(self):
        return self.headers.get("x-embed-lane") or LANE

    def do_GET(self):
        if self.path == "/health":
            now = time.time()
            with _lock:
                st = {u: dict(s) for u, s in _stats.items()}
            for s in st.values():
                s["dead"] = s["dead_until"] > now
            return self._send(200, json.dumps(
                {"ok": True, "upstreams": UPSTREAMS,
                 "defer_upstreams": DEFER_UPSTREAMS,
                 "defer_after_ms": int(DEFER_AFTER_S * 1000),
                 "timeout_s": TIMEOUT, "lane": LANE,
                 "stats": st}).encode())
        # pass-through GETs (e.g. /api/tags, /api/ps, /api/version)
        _, st, data = _first(self.path, None, self._lane())
        self._send(st, data)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path in RACED:
            _, st, data = _race(self.path, body, self._lane())
        else:
            _, st, data = _first(self.path, body, self._lane())
        self._send(st, data)


def main():
    if not UPSTREAMS and not DEFER_UPSTREAMS:
        raise SystemExit("EMBED_POOL_UPSTREAMS and EMBED_POOL_DEFER_UPSTREAMS "
                         "are both empty — set at least one upstream")
    host, port = ADDR.rsplit(":", 1)
    srv = ThreadingHTTPServer((host, int(port)), H)
    print(f"embed-pool-shim on {ADDR} racing {len(UPSTREAMS)} primaries + "
          f"{len(DEFER_UPSTREAMS)} deferred (after {DEFER_AFTER_S}s), "
          f"timeout {TIMEOUT}s")
    srv.serve_forever()


if __name__ == "__main__":
    main()
