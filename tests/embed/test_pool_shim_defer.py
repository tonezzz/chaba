"""Unit tests for embed-pool-shim's deferred tier (MEM-0805 lane B).
Local stub HTTP servers only — verifies deferred upstreams join the
/api/embed race after DEFER_AFTER_S and never before."""
import importlib.util
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


shim = load("embed_pool_shim", "scripts/nest/embed-pool-shim.py")


def _stub(delay_s, tag):
    """Tiny ollama-shaped /api/embed stub; records hit times."""
    hits = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            hits.append(time.time())
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            time.sleep(delay_s)
            body = json.dumps({"embeddings": [[tag]]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", hits


class DeferTier(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(shim, k) for k in
                       ("UPSTREAMS", "DEFER_UPSTREAMS", "DEFER_AFTER_S",
                        "TIMEOUT", "DEAD_AFTER", "DEAD_COOLDOWN_S")}
        self._stats_saved = dict(shim._stats)
        shim.TIMEOUT = 5
        shim.DEAD_AFTER = 99
        shim.DEAD_COOLDOWN_S = 60
        shim.DEFER_AFTER_S = 0.4

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(shim, k, v)
        shim._stats.clear()
        shim._stats.update(self._stats_saved)

    def _wire(self, primaries, deferred):
        shim.UPSTREAMS = primaries
        shim.DEFER_UPSTREAMS = deferred
        shim._stats.clear()
        for u in primaries + deferred:
            shim._stats[u] = {"wins": 0, "fails": 0, "last_ms": 0,
                              "consec": 0, "dead_until": 0.0}

    def test_deferred_waits_for_primary(self):
        fast_p, hits_p = _stub(0.05, 1)
        slow_d, hits_d = _stub(0.05, 2)
        self._wire([fast_p], [slow_d])
        t0 = time.time()
        u, st, data = shim._race("/api/embed", b"{}")
        self.assertEqual(st, 200)
        self.assertEqual(u, fast_p)
        # primary won well before the defer window — deferred never fired
        self.assertLess(time.time() - t0, shim.DEFER_AFTER_S)
        self.assertEqual(hits_d, [])
        self.assertEqual(len(hits_p), 1)

    def test_deferred_joins_when_primaries_slow(self):
        slow_p, hits_p = _stub(3.0, 1)
        fast_d, hits_d = _stub(0.05, 2)
        self._wire([slow_p], [fast_d])
        t0 = time.time()
        u, st, data = shim._race("/api/embed", b"{}")
        elapsed = time.time() - t0
        self.assertEqual(st, 200)
        self.assertEqual(u, fast_d)
        self.assertGreaterEqual(elapsed, shim.DEFER_AFTER_S)
        self.assertEqual(len(hits_d), 1)

    def test_no_defer_config_races_primaries_only(self):
        fast_p, hits_p = _stub(0.05, 1)
        slow_p2, hits_p2 = _stub(3.0, 9)
        self._wire([fast_p, slow_p2], [])
        u, st, _ = shim._race("/api/embed", b"{}")
        self.assertEqual(st, 200)
        self.assertEqual(u, fast_p)


if __name__ == "__main__":
    unittest.main()
