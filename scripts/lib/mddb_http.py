#!/usr/bin/env python3
"""mddb_http.py — shared MDDB /v1 JSON POST with bounded transient retry.

The idc03 CMS publish timers (chaba-starboard-tracker,
chaba-cached-videos) intermittently die with
`error: Remote end closed connection without response`
(http.client.RemoteDisconnected) when the MDDB backend drops the
connection mid-request — the next timer tick succeeds, so the failure
is transient, not content (card
cms-publish-remote-end-closed-fix-unpinned / KNB-1484).

Transport-level failures get a bounded retry with backoff; HTTP
errors (any non-2xx, incl. 5xx) and non-network exceptions still raise
on the first failure so real errors stay loud — a genuine outage must
never be masked as a quiet success.

Stdlib only.
"""
from __future__ import annotations

import http.client
import json
import sys
import time
import urllib.error
import urllib.request

# Transient transport failures safe to retry. urlopen raises
# RemoteDisconnected/IncompleteRead/reset errors raw from getresponse()
# and wraps connect-stage socket errors in URLError — both are covered.
# HTTPError is a URLError subclass: the except order below keeps every
# non-2xx loud and unretried.
_RETRYABLE = (
    urllib.error.URLError,
    http.client.RemoteDisconnected,
    http.client.IncompleteRead,
    ConnectionResetError,
    ConnectionAbortedError,
    TimeoutError,
)

# Sleep before retry N (0-based attempt index). Worst case adds
# sum(delays) ~= 62s per call — still trivial vs the 15m oneshot
# timeouts, and long enough to ride out the mddb-cms congestion
# bursts that produce the connection closes (embedding-backlog
# windows observed running minutes, not seconds).
_BACKOFF_S = (2, 4, 8, 16, 32)


def post(base, path, payload, timeout=60, retries=len(_BACKOFF_S)):
    """POST {base}/{path} a JSON payload; return the decoded response.

    Retries only transport-close/reset/timeout failures, up to
    `retries` extra attempts with _BACKOFF_S delays. HTTPError and any
    other exception propagate immediately.
    """
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{base}/{path}", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except urllib.error.HTTPError:
            raise
        except _RETRYABLE as e:
            last = e
            if attempt >= retries:
                break
            delay = _BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)]
            print(f"warn: mddb {path} attempt {attempt + 1}/"
                  f"{retries + 1} failed ({e}) — retry in {delay}s",
                  file=sys.stderr)
            time.sleep(delay)
    raise last
