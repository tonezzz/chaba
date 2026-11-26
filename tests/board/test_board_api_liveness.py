"""Regression tests for the board-api accept-loop wedge fix
(card board-api-accept-loop-wedge-auto-restart-7dd2f1).

2026-11-26 idc03: the main thread parked inside Thread.start() ->
_started.wait() (socketserver process_request) and every door
503/504'd for ~20min until a manual restart. BoardAPIHTTPServer moves
the spawn onto a bounded worker pool so a wedged start() parks a
worker — never serve_forever — and a liveness watchdog restarts the
process when no door can be served.

Covers: a stuck spawn no longer blocks other doors, spawn exceptions
are non-fatal, the watchdog fires recovery on a full spawn wedge, and
the post-restart drain posts exactly one board comms per wedge.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "board_api_liveness", REPO / "scripts" / "board" / "board-api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE_CARDS = [
    {"id": "c-one", "title": "One", "column": "doing",
     "updated": "2026-11-26 08:00"},
]


def _is_handler_spawn(thread_self) -> bool:
    """True when thread_self is a socketserver handler thread — its
    _target is the server's process_request_thread bound method."""
    tgt = getattr(thread_self, "_target", None)
    return getattr(tgt, "__name__", "") == "process_request_thread"


class _ServerCase(unittest.TestCase):
    """BoardAPIHTTPServer on an ephemeral port, mod.H handler, tmp
    card store — same fixture shape as test_board_api_reads."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls._saved = {
            "CARDS_JSON": cls.mod.CARDS_JSON,
            "CARD_DIR": cls.mod.CARD_DIR,
            "LOCK": cls.mod.LOCK,
            "INBOX_DIR": cls.mod.INBOX_DIR,
            "WATCHDOG_DIR": cls.mod.WATCHDOG_DIR,
            "ALERT_CARD": cls.mod.ALERT_CARD,
            "LIVENESS_DISABLED": cls.mod.LIVENESS_DISABLED,
        }
        fixture = t / "cards.json"
        fixture.write_text(json.dumps(
            {"generated": "2026-11-26 08:00", "page_version": 1,
             "columns": [], "cards": FIXTURE_CARDS}))
        cls.mod.CARDS_JSON = fixture
        cls.mod.CARD_DIR = t / "cards"
        cls.mod.CARD_DIR.mkdir()
        cls.mod.LOCK = t / "board-api.lock"
        cls.mod.INBOX_DIR = t / "focus-inbox"
        cls.mod.INBOX_DIR.mkdir()
        cls.mod.WATCHDOG_DIR = t / "watchdog"
        cls.mod.ALERT_CARD = "board-api-watchdog-alerts"
        cls.mod.LIVENESS_DISABLED = True   # spawn tests opt out

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved.items():
            setattr(cls.mod, k, v)
        cls.tmp.cleanup()

    def setUp(self):
        for path in self.mod.CARD_DIR.glob("*.yml"):
            path.unlink()
        for card in FIXTURE_CARDS:
            (self.mod.CARD_DIR / f"{card['id']}.yml").write_text(
                json.dumps(card))
        # the alert card the watchdog drain posts to
        (self.mod.CARD_DIR / "board-api-watchdog-alerts.yml").write_text(
            json.dumps({"id": "board-api-watchdog-alerts",
                        "title": "board-api watchdog alerts",
                        "column": "done", "comms": []}))
        self.mod.WATCHDOG_DIR.mkdir(parents=True, exist_ok=True)
        for old in self.mod.WATCHDOG_DIR.glob("*"):
            old.unlink()

    def _serve(self, server_cls=None):
        srv = (server_cls or self.mod.BoardAPIHTTPServer)(
            ("127.0.0.1", 0), self.mod.H)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        return srv, srv.server_address[1]

    def get(self, port, path, timeout=5):
        url = f"http://127.0.0.1:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _raw_get(self, port, path, timeout=8):
        """GET that tolerates a dropped connection — a spawn failure
        closes the request socket, so urllib raises."""
        try:
            return self.get(port, path, timeout=timeout)
        except Exception as e:
            return ("error", repr(e))


class SpawnIsolationTest(_ServerCase):
    def test_stuck_spawn_does_not_block_other_doors(self):
        """The incident mode: Thread.start() parks inside
        _started.wait(). With the spawn pool, one stuck start() parks a
        spawner worker — the accept loop and every other door stay up."""
        real_start = threading.Thread.start
        entered = threading.Event()
        gate = threading.Event()
        calls = {"n": 0}

        def fake_start(self):
            if _is_handler_spawn(self):
                calls["n"] += 1
                if calls["n"] == 1:
                    entered.set()
                    gate.wait(15)          # parked spawner
                    raise RuntimeError("simulated stuck spawn")
            return real_start(self)

        srv, port = self._serve()
        with mock.patch.object(threading.Thread, "start", fake_start):
            # first request parks a spawner inside start()
            stuck = []
            t = threading.Thread(
                target=lambda: stuck.append(
                    self._raw_get(port, "/cards")),
                daemon=True)
            t.start()
            self.assertTrue(entered.wait(5), "spawn never reached start()")
            time.sleep(0.2)              # let it park inside start()
            # other doors still answer while the spawn is stuck
            st, body = self.get(port, "/health")
            self.assertEqual((st, body), (200, {"ok": True}))
            st, body = self.get(port, "/cards?id=c-one&compact=1")
            self.assertEqual(st, 200)
            self.assertEqual(body["cards"][0]["id"], "c-one")
            # releasing the stuck spawn fails ONLY that request —
            # the worker closes the socket and keeps draining the queue
            gate.set()
            t.join(10)
            # the stuck spawn failed -> its socket was closed, not served
            self.assertTrue(stuck)
            self.assertEqual(stuck[0][0], "error")
            st, body = self.get(port, "/health")
            self.assertEqual(st, 200)

    def test_spawn_exception_is_non_fatal(self):
        """Thread.start() raising must close only that request — the
        accept loop keeps serving (previously an escaping exception
        killed serve_forever outright)."""
        real_start = threading.Thread.start
        state = {"fails": 2}

        def fake_start(self):
            if _is_handler_spawn(self) and state["fails"] > 0:
                state["fails"] -= 1
                raise RuntimeError("can't start new thread")
            return real_start(self)

        srv, port = self._serve()
        with mock.patch.object(threading.Thread, "start", fake_start):
            for _ in range(state["fails"] + 1):
                try:
                    self.get(port, "/health", timeout=3)
                except Exception:
                    pass          # failed spawn -> dropped connection
            st, body = self.get(port, "/health")
            self.assertEqual((st, body), (200, {"ok": True}))


class WatchdogRecoveryTest(_ServerCase):
    def test_wedged_spawn_triggers_watchdog_recovery(self):
        """Full wedge: EVERY handler spawn parks -> no door can be
        served -> the liveness watchdog fires recovery once."""
        mod = self.mod
        # fast watchdog cadence for the test
        saved = {k: getattr(mod, k) for k in (
            "LIVENESS_INTERVAL_S", "LIVENESS_TIMEOUT_S",
            "LIVENESS_FAILS", "LIVENESS_DISABLED")}
        mod.LIVENESS_INTERVAL_S = 0.1
        mod.LIVENESS_TIMEOUT_S = 0.3
        mod.LIVENESS_FAILS = 2
        mod.LIVENESS_DISABLED = False
        wedged = threading.Event()
        fires = []

        class _WedgedServer(mod.BoardAPIHTTPServer):
            def _on_liveness_wedge(self):
                fires.append(time.monotonic())
                mod._watchdog_alert_record("test wedge")
                wedged.set()
                # production path exits the process; the stub returns

        real_start = threading.Thread.start

        def fake_start(self):
            if _is_handler_spawn(self):
                threading.Event().wait()   # parked forever
            return real_start(self)

        try:
            srv, port = self._serve(_WedgedServer)
            with mock.patch.object(threading.Thread, "start",
                                   fake_start):
                # one request parks a spawner; probes then can't be
                # served either — consecutive failures -> recovery
                threading.Thread(
                    target=lambda: self._raw_get(port, "/health"),
                    daemon=True).start()
                self.assertTrue(wedged.wait(15),
                                "watchdog never fired recovery")
                # latch: further probe failures must not re-fire
                time.sleep(0.6)
                self.assertEqual(len(fires), 1)
                # the pending alert record the drain will deliver
                recs = [json.loads(l) for l in
                        (mod.WATCHDOG_DIR / "alerts.jsonl")
                        .read_text().splitlines() if l.strip()]
                self.assertEqual(len(recs), 1)
                self.assertEqual(recs[0]["reason"], "test wedge")
        finally:
            for k, v in saved.items():
                setattr(mod, k, v)


class WatchdogAlertDrainTest(_ServerCase):
    def test_drain_posts_one_comms_per_wedge(self):
        mod = self.mod
        with mock.patch.object(mod, "_queue_commit"), \
                mock.patch.object(mod, "commit_async"), \
                mock.patch.object(mod, "render_async"):
            rec = {"at": "2026-11-26 09:00", "epoch": 1764241200.0,
                   "pid": 4321,
                   "reason": "liveness probe failed 3 consecutive checks"}
            (mod.WATCHDOG_DIR / "alerts.jsonl").write_text(
                json.dumps(rec) + "\n")
            mod._drain_watchdog_alerts()
            card = mod.load(
                mod.CARD_DIR / "board-api-watchdog-alerts.yml")
            hits = [c for c in card["comms"]
                    if "watchdog" in str(c.get("text"))]
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["from"], "chaba")
            self.assertIn("liveness probe failed 3", hits[0]["text"])
            # file consumed — a second drain posts nothing new
            mod._drain_watchdog_alerts()
            card = mod.load(
                mod.CARD_DIR / "board-api-watchdog-alerts.yml")
            hits = [c for c in card["comms"]
                    if "watchdog" in str(c.get("text"))]
            self.assertEqual(len(hits), 1)

    def test_drain_falls_back_to_inbox_when_card_missing(self):
        mod = self.mod
        mod.ALERT_CARD = "no-such-alert-card"
        try:
            with mock.patch.object(mod, "_queue_commit"), \
                    mock.patch.object(mod, "commit_async"), \
                    mock.patch.object(mod, "render_async"):
                rec = {"at": "2026-11-26 09:00", "epoch": 1764241300.0,
                       "pid": 4321, "reason": "wedge"}
                (mod.WATCHDOG_DIR / "alerts.jsonl").write_text(
                    json.dumps(rec) + "\n")
                mod._drain_watchdog_alerts()
                files = list(mod.INBOX_DIR.glob("*.yml"))
                self.assertEqual(len(files), 1)
                entry = mod.yaml.safe_load(files[0].read_text())
                self.assertIn("watchdog", entry["title"])
        finally:
            mod.ALERT_CARD = "board-api-watchdog-alerts"


if __name__ == "__main__":
    unittest.main()
