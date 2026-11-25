"""Unit tests for embed-pool-shim's deferred tier (MEM-0805 lane B).
Local stub HTTP servers only — verifies deferred upstreams join the
/api/embed race after DEFER_AFTER_S and never before."""
import importlib.util
import json
import socket
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
            try:
                self.wfile.write(body)
            except OSError:
                pass  # client (race loser) already hung up

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

    def test_losing_call_is_cancelled_not_counted_as_failure(self):
        """A race loser must not burn TIMEOUT seconds of upstream CPU nor
        be recorded as a failed call (the latter tripped dead-cooldown on
        con01 after 3 lost races and took a healthy upstream out of the
        pool). Regression for the bge-m3 timeout storm."""
        fast_p, hits_p = _stub(0.05, 1)
        slow_p2, hits_p2 = _stub(3.0, 9)
        self._wire([fast_p, slow_p2], [])
        t0 = time.time()
        u, st, _ = shim._race("/api/embed", b"{}")
        elapsed = time.time() - t0
        self.assertEqual(st, 200)
        self.assertEqual(u, fast_p)
        self.assertLess(elapsed, 1.0, "race waited for the losing call")
        # Give the loser's worker a moment to unwind and record its result.
        time.sleep(0.3)
        self.assertEqual(shim._stats[slow_p2]["fails"], 0,
                         "cancelled loser was counted as an upstream failure")
        self.assertEqual(shim._stats[slow_p2]["consec"], 0)
        self.assertEqual(shim._stats[fast_p]["wins"], 1)

    def test_loser_socket_is_shut_down_at_connect_time(self):
        """Proves the cancellation is socket-level, not just a response
        handle close. ollama sends headers only AFTER computing, so a loser
        has no response object to close — its raw socket must be shut down.
        This test fails with any fix that only closes urllib responses."""
        captured = {}
        real_abort = shim._abort_inflight

        def spy(winner_sock, sockets):
            captured["winner"] = winner_sock
            captured["sockets"] = list(sockets)
            return real_abort(winner_sock, sockets)

        shim._abort_inflight = spy
        try:
            fast_p, _ = _stub(0.05, 1)
            slow_p2, _ = _stub(3.0, 9)
            self._wire([fast_p, slow_p2], [])
            u, st, _ = shim._race("/api/embed", b"{}")
            self.assertEqual(st, 200)
            self.assertEqual(u, fast_p)
            time.sleep(0.2)
            # The winner removes its own socket from the list on completion,
            # so what remains at cancellation time are the losers.
            self.assertGreaterEqual(len(captured["sockets"]), 1)
            losers = [s for s, _ in captured["sockets"]
                      if s is not captured["winner"]]
            self.assertTrue(losers, "no losing socket was captured")
            for s in losers:
                # A shut-down socket rejects sends immediately; with the
                # old code the loser's socket stayed open for the full 3s.
                with self.assertRaises(OSError):
                    s.send(b"x")
        finally:
            shim._abort_inflight = real_abort


def _flaky_stub():
    """Ollama-shaped stub that 500s while state['fail'] is set and 200s
    after — exercises the dead-cooldown breaker without real network
    failures. Returns (url, state, server)."""
    state = {"fail": True, "hits": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            state["hits"] += 1
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if state["fail"]:
                body, code = b'{"error":"boom"}', 500
            else:
                body = json.dumps({"embeddings": [[2]]}).encode()
                code = 200
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass  # client (race loser) already hung up

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", state, srv


class DeadCooldown(unittest.TestCase):
    """Circuit breaker (card embed-pool-shim-fast-fail-for-dead-upstr,
    soak 2026-11-08): DEAD_AFTER consecutive failures parks an upstream
    for DEAD_COOLDOWN_S — it is excluded from races while parked, gets a
    half-open retry after the cooldown, and a win resets the streak."""

    def setUp(self):
        self._saved = {k: getattr(shim, k) for k in
                       ("UPSTREAMS", "DEFER_UPSTREAMS", "DEFER_AFTER_S",
                        "TIMEOUT", "DEAD_AFTER", "DEAD_COOLDOWN_S")}
        self._stats_saved = dict(shim._stats)
        shim.TIMEOUT = 5
        shim.DEFER_UPSTREAMS = []
        shim.DEFER_AFTER_S = 60
        shim.DEAD_AFTER = 2
        shim.DEAD_COOLDOWN_S = 0.4

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

    def test_failing_upstream_parks_and_sits_out(self):
        flaky, state, srv = _flaky_stub()
        fast, _ = _stub(0.05, 1)
        self._wire([flaky, fast], [])
        try:
            for _ in range(shim.DEAD_AFTER):
                u, st, _ = shim._race("/api/embed", b"{}")
                self.assertEqual(st, 200)
                self.assertEqual(u, fast)  # 500s never win the race
            self.assertEqual(state["hits"], shim.DEAD_AFTER)
            self.assertGreater(shim._stats[flaky]["dead_until"],
                               time.time())
            # Parked: further races must not spawn it at all.
            for _ in range(3):
                shim._race("/api/embed", b"{}")
            self.assertEqual(state["hits"], shim.DEAD_AFTER)
            self.assertEqual(shim._stats[flaky]["fails"],
                             shim.DEAD_AFTER)
        finally:
            srv.shutdown()

    def test_parked_upstream_half_opens_and_recovers(self):
        flaky, state, srv = _flaky_stub()
        fast, _ = _stub(0.05, 1)
        self._wire([flaky, fast], [])
        try:
            for _ in range(shim.DEAD_AFTER):
                shim._race("/api/embed", b"{}")
            parked_hits = state["hits"]
            state["fail"] = False  # upstream recovers during cooldown
            time.sleep(shim.DEAD_COOLDOWN_S + 0.15)
            u, st, _ = shim._race("/api/embed", b"{}")
            self.assertEqual(st, 200)
            # Recovered upstream answers instantly — wins the half-open race.
            self.assertEqual(u, flaky)
            self.assertGreater(state["hits"], parked_hits)
            st_flaky = shim._stats[flaky]
            self.assertEqual(st_flaky["consec"], 0)
            self.assertEqual(st_flaky["dead_until"], 0.0)
            self.assertEqual(st_flaky["wins"], 1)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
