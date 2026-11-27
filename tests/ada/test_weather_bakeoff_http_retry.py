"""Unit tests for scripts/ada/weather-bakeoff.py http_json/http_bytes —
bounded retry on transient transport failures (card
weather-bakeoff-ha-config-bounded-retry).

kraut-rain-watch died twice on idc03 with
`ConnectionResetError [Errno 104]` reading {ha_url}/api/config — the HA
API read has no retry, so a single dropped connection kills the run
before rain_check() executes. http_json()/http_bytes() must absorb that
class of failure within <=3 attempts / <=5s added delay, must NOT absorb
4xx or non-transient errors, and must not change the success path.
"""

from __future__ import annotations

import importlib.util
import io
import json
import socket
import urllib.error
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/weather-bakeoff.py"

spec = importlib.util.spec_from_file_location("weather_bakeoff", SCRIPT)
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)


def _ok(payload=None):
    return io.BytesIO(json.dumps(payload or {"ok": True}).encode())


def _json(url="http://ha.test/api/config", **kw):
    return wb.http_json(url, **kw)


def test_reset_then_success():
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionResetError(104, "Connection reset by peer")
        return _ok({"latitude": 12.6, "longitude": 101.1})

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(wb.time, "sleep") as slp:
        assert _json() == {"latitude": 12.6, "longitude": 101.1}
    assert len(calls) == 2
    assert slp.call_count == 1


def test_persistent_failure_raises_last_error():
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        raise urllib.error.URLError(socket.timeout("timed out"))

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(wb.time, "sleep") as slp:
        try:
            _json()
        except urllib.error.URLError:
            pass
        else:
            raise AssertionError("persistent failure must raise")
    assert len(calls) == wb._RETRY_ATTEMPTS == 3
    assert slp.call_count == 2
    # exponential backoff, bounded well under 5s total
    delays = [c.args[0] for c in slp.call_args_list]
    assert delays == [0.5, 1.0]
    assert sum(delays) <= 5.0


def test_http_5xx_retried_then_success():
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(
                "http://ha.test/api/config", 503, "unavailable", {}, None)
        return _ok({"ok": True})

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(wb.time, "sleep"):
        assert _json() == {"ok": True}
    assert len(calls) == 3


def test_http_4xx_raises_immediately():
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        raise urllib.error.HTTPError(
            "http://ha.test/api/config", 401, "unauthorized", {}, None)

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(wb.time, "sleep") as slp:
        try:
            _json()
        except urllib.error.HTTPError as e:
            assert e.code == 401
        else:
            raise AssertionError("HTTPError must propagate")
    assert len(calls) == 1
    assert slp.call_count == 0


def test_non_transient_error_raises_immediately():
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        raise ValueError("bad payload")

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(wb.time, "sleep") as slp:
        try:
            _json()
        except ValueError:
            pass
        else:
            raise AssertionError("ValueError must propagate")
    assert len(calls) == 1
    assert slp.call_count == 0


def test_http_bytes_shares_retry():
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionResetError(104, "reset")
        return io.BytesIO(b"<xml/>")

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(wb.time, "sleep"):
        assert wb.http_bytes("http://tmd.test/feed") == b"<xml/>"
    assert len(calls) == 2


def test_success_path_single_attempt():
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        return _ok({"a": 1})

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(wb.time, "sleep") as slp:
        assert _json() == {"a": 1}
    assert len(calls) == 1
    assert slp.call_count == 0
