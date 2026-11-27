"""Unit tests for the MDDB readiness gate in scripts/ada/media-inbox-update.py
(card mddb-idc03-oom-coldstart-publisher-window).

mddb's early health listener serves /v1/health during startup but 404s
every other route until 'mddb HTTP listening' (~104s after the 2026-11-27
OOM-kill restarts on idc03). _post must wait out that window instead of
dying on HTTP 404 / RemoteDisconnected, while real errors stay loud.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/media-inbox-update.py"

spec = importlib.util.spec_from_file_location("media_inbox_update", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["media_inbox_update"] = mod
spec.loader.exec_module(mod)


def _http_error(code):
    return urllib.error.HTTPError(
        "http://mddb.test/v1/add", code, "err", {}, io.BytesIO(b"{}"))


def _ok(payload=None):
    return io.BytesIO(json.dumps(payload or {"ok": True}).encode())


class _Resp:
    """Minimal urlopen response: context manager + .status + .read()."""

    def __init__(self, status=200, payload=None):
        self.status = status
        self._buf = io.BytesIO(json.dumps(payload or {"ok": True}).encode())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._buf.read()


class TestHealthy:
    def test_200_is_healthy(self):
        with mock.patch.object(urllib.request, "urlopen",
                               return_value=_Resp(200)):
            assert mod._healthy() is True

    def test_503_warming_up_is_not_healthy(self):
        def fake(req, timeout=None):
            raise _http_error(503)
        with mock.patch.object(urllib.request, "urlopen", fake):
            assert mod._healthy() is False

    def test_conn_refused_is_not_healthy(self):
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=ConnectionRefusedError()):
            assert mod._healthy() is False


class TestWaitReady:
    def test_returns_true_when_already_ready(self):
        with mock.patch.object(mod, "_healthy", return_value=True), \
                mock.patch.object(mod.time, "sleep") as slp:
            assert mod.wait_ready() is True
        slp.assert_not_called()

    def test_polls_until_healthy(self):
        with mock.patch.object(mod, "_healthy",
                               side_effect=[False, False, True]), \
                mock.patch.object(mod.time, "sleep") as slp:
            assert mod.wait_ready(budget=60) is True
        assert slp.call_count == 2

    def test_returns_false_when_budget_expires(self):
        with mock.patch.object(mod, "_healthy", return_value=False), \
                mock.patch.object(mod.time, "sleep"):
            assert mod.wait_ready(budget=0) is False


class TestPost:
    def _run(self, healthy_seq, post_effects, wait_ready=None):
        """Drive _post with _healthy/_mddb_post stubbed."""
        posts = []

        def fake_post(base, path, payload, timeout=60, retries=5):
            posts.append((base, path))
            eff = post_effects[len(posts) - 1]
            if isinstance(eff, Exception):
                raise eff
            return eff

        with mock.patch.object(mod, "_healthy",
                               side_effect=list(healthy_seq)), \
                mock.patch.object(mod, "wait_ready",
                                  return_value=True if wait_ready is None
                                  else wait_ready), \
                mock.patch.object(mod, "_mddb_post", fake_post):
            try:
                result = mod._post("add", {"a": 1})
                err = None
            except Exception as e:  # noqa: BLE001 - assert below
                result, err = None, e
        return result, err, posts

    def test_ready_server_posts_first_try(self):
        result, err, posts = self._run(
            healthy_seq=[True], post_effects=[{"ok": True}])
        assert err is None and result == {"ok": True}
        assert posts == [(mod.MDDB, "add")]

    def test_warmup_404_waits_for_ready_then_retries(self):
        result, err, posts = self._run(
            healthy_seq=[False, True],
            post_effects=[_http_error(404), {"ok": True}])
        assert err is None and result == {"ok": True}
        assert len(posts) == 2

    def test_non_404_http_error_raises_immediately(self):
        boom = _http_error(500)
        result, err, posts = self._run(
            healthy_seq=[True], post_effects=[boom])
        assert err is boom and len(posts) == 1

    def test_transport_error_waits_and_retries_once(self):
        result, err, posts = self._run(
            healthy_seq=[True, True],
            post_effects=[ConnectionResetError(104, "reset"),
                          {"ok": True}])
        assert err is None and result == {"ok": True}
        assert len(posts) == 2

    def test_persistent_transport_error_still_raises(self):
        result, err, posts = self._run(
            healthy_seq=[True, True],
            post_effects=[ConnectionResetError(104, "reset"),
                          ConnectionResetError(104, "reset")])
        assert isinstance(err, ConnectionResetError)
        assert len(posts) == 2

    def test_never_ready_raises_runtime_error(self):
        result, err, posts = self._run(
            healthy_seq=[False], post_effects=[], wait_ready=False)
        assert isinstance(err, RuntimeError)
        assert posts == []
