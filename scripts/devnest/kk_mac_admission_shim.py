#!/usr/bin/env python3
"""kkmac-admission-shim — fail-fast healthcheck proxy for the kk-mac ollama lane.

LiteLLM's kk-mac legs point api_base here instead of at the raw SSH tunnel
(:11445). Every request is gated on the Ada Nest admission snapshot
(kk_mac_admission.snapshot): an ineligible node gets an instant 503 so the
router falls back to the paid leg instead of queueing a 120s call on a hot
or busy member device. Eligible requests are proxied through unchanged —
incl. streamed ollama responses.

Gates (snapshot reasons): heartbeat stale >900s / missing, ollama_ok false,
disk_free_gb < 20, load_1m > 4.0, cpu_temp_c > 60, node_busy (tmux_jobs,
load_ok false, or load1/cores > 1.0).

Config (env):
  KK_SHIM_ADDR                listen addr            (default 127.0.0.1:11447)
  KK_SHIM_UPSTREAM            upstream ollama URL    (default http://127.0.0.1:11445)
  KK_SHIM_CACHE_S             admission cache TTL    (default 10)
  KK_SHIM_UPSTREAM_TIMEOUT_S  upstream call timeout  (default 130 — above
                              LiteLLM's 120s leg timeout so semantics stay
                              the caller's, not the shim's)
  KK_ADMISSION_MDDB_URL       heartbeat search URL   (default snapshot()'s)
  KK_ADMISSION_FORCE_DENY     path to a kill-switch file — while it exists
                              every request is denied (drain lane)
  KK_ADMISSION_HEARTBEAT_FILE path to a JSON heartbeat body — replaces the
                              MDDB doc (simulated-heartbeat testing)

Endpoints:
  GET /health   admission snapshot + counters (never gated)
  *   anything  gated proxy to upstream — 503 JSON on deny, 502 on upstream error
"""
import http.client
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kk_mac_admission

ADDR = os.environ.get("KK_SHIM_ADDR", "127.0.0.1:11447")
UPSTREAM = os.environ.get("KK_SHIM_UPSTREAM", "http://127.0.0.1:11445").rstrip("/")
CACHE_S = float(os.environ.get("KK_SHIM_CACHE_S", "10"))
UPSTREAM_TIMEOUT = float(os.environ.get("KK_SHIM_UPSTREAM_TIMEOUT_S", "130"))
MDDB_URL = os.environ.get("KK_ADMISSION_MDDB_URL", "")
FORCE_DENY_FILE = os.environ.get("KK_ADMISSION_FORCE_DENY", "")
HEARTBEAT_FILE = os.environ.get("KK_ADMISSION_HEARTBEAT_FILE", "")

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate",
              "proxy-authorization", "te", "trailer", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length"}
# Content-Length is NOT stripped from upstream responses — the body is
# forwarded verbatim so the advertised length stays accurate; when the
# upstream reply is chunked/length-less the body is close-delimited.
RESP_STRIP = HOP_BY_HOP - {"content-length"}

_cache = {"at": 0.0, "snap": None}
_stats = {"admitted": 0, "denied": 0, "proxied": 0, "upstream_errors": 0,
          "started": time.time()}
_lock = threading.Lock()


def _admission() -> dict:
    force = FORCE_DENY_FILE and os.path.exists(FORCE_DENY_FILE)
    with _lock:
        if not force and _cache["snap"] is not None \
                and time.time() - _cache["at"] < CACHE_S:
            return _cache["snap"]
    try:
        kw = {}
        if MDDB_URL:
            kw["url"] = MDDB_URL
        if HEARTBEAT_FILE:
            body = json.loads(open(HEARTBEAT_FILE).read())
            kw["docs"] = [{"contentMd": json.dumps(body)}]
        snap = kk_mac_admission.snapshot(**kw)
    except Exception as exc:
        snap = {"eligible": False,
                "reasons": [f"admission_error:{type(exc).__name__}"],
                "host": "KKs-Mac-Studio"}
    if force:
        snap = dict(snap, eligible=False,
                    reasons=snap.get("reasons", []) + ["force_deny"])
    with _lock:
        _cache["at"], _cache["snap"] = time.time(), snap
        _stats["admitted" if snap.get("eligible") else "denied"] += 1
    return snap


def _upstream_conn():
    host, _, rest = UPSTREAM.partition("://")
    h, _, p = rest.partition(":")
    return http.client.HTTPConnection(h, int(p or 80),
                                      timeout=UPSTREAM_TIMEOUT)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "kkmac-admission-shim/1.0"

    def _reply(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _gate(self):
        snap = _admission()
        if snap.get("eligible"):
            return snap
        # drain the unread request body so keep-alive doesn't parse it as
        # a new request line, then close — denial is terminal anyway.
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(min(length, 1 << 24))
        self.close_connection = True
        self._reply(503, {"error": {
            "message": "kk-mac admission denied: "
                       + "+".join(snap.get("reasons") or ["unknown"]),
            "type": "admission_denied",
            "code": "kk_mac_unavailable",
            "reasons": snap.get("reasons", []),
        }})
        return None

    def _health(self):
        self._reply(200, {
            "ok": True,
            "admission": _admission(),
            "upstream": UPSTREAM,
            "stats": {k: (round(v, 1) if k == "started" else v)
                      for k, v in _stats.items()},
        })

    def _proxy(self):
        if self.path in ("/health", "/healthz"):
            self._health()
            return
        if self._gate() is None:
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP_BY_HOP}
        try:
            conn = _upstream_conn()
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            with _lock:
                _stats["upstream_errors"] += 1
            self._reply(502, {"error": {
                "message": f"kk-mac upstream unreachable: {exc}",
                "type": "upstream_error",
                "code": "kk_mac_upstream_down"}})
            return
        with _lock:
            _stats["proxied"] += 1
        # Pass the response through; streamed/chunked upstream replies get a
        # close-delimited body so clients still see incremental delivery.
        resp_headers = [(k, v) for k, v in resp.getheaders()
                        if k.lower() not in RESP_STRIP]
        has_len = resp.getheader("Content-Length") is not None
        self.send_response(resp.status)
        for k, v in resp_headers:
            self.send_header(k, v)
        if not has_len:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        try:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _proxy

    def log_message(self, fmt, *args):
        sys.stderr.write("kkmac-shim %s - %s\n"
                         % (self.address_string(), fmt % args))


def main():
    host, _, port = ADDR.rpartition(":")
    srv = ThreadingHTTPServer((host or "127.0.0.1", int(port)), Handler)
    sys.stderr.write("kkmac-admission-shim on %s -> %s\n" % (ADDR, UPSTREAM))
    srv.serve_forever()


if __name__ == "__main__":
    main()
