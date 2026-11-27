"""Unit tests for scripts/lib/mddb_http.py — bounded retry on transient
connection-close errors for the CMS publish HTTP calls
(card cms-publish-remote-end-closed-fix-unpinned / KNB-1484).

The idc03 chaba-starboard-tracker / chaba-cached-videos oneshots died
with `Remote end closed connection without response` (exit=1) while
earlier and later runs published fine — a transient MDDB drop, not bad
content. post() must absorb that class of failure and must NOT absorb
HTTP errors or unrelated exceptions.
"""

from __future__ import annotations

import http.client
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from lib import mddb_http  # noqa: E402


def _ok(payload=None):
    return io.BytesIO(json.dumps(payload or {"ok": True}).encode())


def _post(**kw):
    return mddb_http.post("http://mddb.test/v1", "add", {"a": 1}, **kw)


def test_remote_disconnect_retries_then_succeeds():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise http.client.RemoteDisconnected(
                "Remote end closed connection without response")
        return _ok()

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(mddb_http.time, "sleep") as slp:
        assert _post() == {"ok": True}
    assert len(calls) == 3
    assert slp.call_count == 2


def test_connection_reset_and_urlerror_retried():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionResetError(104, "Connection reset by peer")
        if len(calls) == 2:
            raise urllib.error.URLError(TimeoutError("timed out"))
        return _ok({"done": 1})

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(mddb_http.time, "sleep"):
        assert _post() == {"done": 1}
    assert len(calls) == 3


def test_http_error_raises_immediately():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError(
            "http://mddb.test/v1/add", 503, "unavailable", {}, None)

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(mddb_http.time, "sleep") as slp:
        try:
            _post()
        except urllib.error.HTTPError as e:
            assert e.code == 503
        else:
            raise AssertionError("HTTPError must propagate")
    assert len(calls) == 1
    assert slp.call_count == 0


def test_non_retryable_exception_raises_immediately():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise ValueError("bad payload")

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(mddb_http.time, "sleep") as slp:
        try:
            _post()
        except ValueError:
            pass
        else:
            raise AssertionError("ValueError must propagate")
    assert len(calls) == 1
    assert slp.call_count == 0


def test_retries_bounded_then_raises_last_error():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise http.client.RemoteDisconnected("closed")

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(mddb_http.time, "sleep") as slp:
        try:
            _post()
        except http.client.RemoteDisconnected:
            pass
        else:
            raise AssertionError("persistent failure must raise")
    # 1 initial + len(_BACKOFF_S) retries
    assert len(calls) == 1 + len(mddb_http._BACKOFF_S)
    assert slp.call_count == len(mddb_http._BACKOFF_S)


def test_custom_retries_bound():
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise http.client.IncompleteRead(b"partial")

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
            mock.patch.object(mddb_http.time, "sleep"):
        try:
            _post(retries=1)
        except http.client.IncompleteRead:
            pass
        else:
            raise AssertionError("persistent failure must raise")
    assert len(calls) == 2
