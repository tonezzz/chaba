#!/usr/bin/env python3
"""mddb embed-path probe — POSTs /v1/vector-search every run and writes an
ops-event doc to ada-ha-events-tony on state TRANSITIONS (up->down, or
down->up recovery). Catches the silent-quota failure class: 2026-09-28
the OpenRouter key hit its spend limit (403) while the Gemini fallback
429'd — the vector index was loaded and healthy, only query embedding
was dead, so nothing noticed until a manual benchmark.

State: ~/.local/share/ada/embed-probe.state ("up" | "down")
Usage: python3 embed-probe.py          # probe once (systemd oneshot)
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023")
MDDB = MDDB.removesuffix("/v1").removesuffix("/")
PROBE_COLLECTION = "ada-ha-bank-general"
PROBE_QUERY = "ada memory recall probe"
EVENTS_COLLECTION = os.environ.get("ADA_OPS_COLLECTION", "ada-ha-events-tony")
STATE = os.path.expanduser("~/.local/share/ada/embed-probe.state")


def _post(path: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        MDDB + path, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _emit(ev_type: str, detail: str) -> None:
    now = datetime.now(timezone.utc).astimezone()
    try:
        _post("/v1/add", {
            "collection": EVENTS_COLLECTION,
            "key": f"ops-embed-probe-{ev_type}-{now:%Y%m%d%H%M%S}",
            "lang": "en", "contentMd": detail,
            "meta": {"kind": ["ops-event"], "type": [ev_type],
                     "instance": ["tony"], "session_id": ["embed-probe"],
                     "ts": [now.isoformat(timespec="seconds")]},
        })
    except Exception as exc:  # emit must never kill the probe
        print(f"ops event write failed: {exc}", file=sys.stderr)


def probe() -> tuple[bool, str]:
    try:
        res = _post("/v1/vector-search", {
            "collection": PROBE_COLLECTION, "query": PROBE_QUERY,
            "topK": 3, "includeContent": False}, timeout=60)
    except Exception as exc:
        return False, f"request failed: {exc}"
    if isinstance(res, dict) and res.get("error"):
        return False, str(res["error"])[:300]
    hits = res.get("results") or res.get("documents") or (
        res if isinstance(res, list) else [])
    if not hits:
        return False, "vector-search returned 0 hits (index empty?)"
    return True, f"{len(hits)} hits"


def main() -> int:
    ok, detail = probe()
    try:
        prev = open(STATE).read().strip()
    except OSError:
        prev = "unknown"
    cur = "up" if ok else "down"
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    open(STATE, "w").write(cur)

    if prev != cur:
        ev_type = "embed_recovered" if ok else "embed_outage"
        _emit(ev_type,
              f"vector-search {'recovered' if ok else 'FAILING'} — {detail}")
        print(f"transition {prev}->{cur}: {ev_type}: {detail}")
    else:
        print(f"{cur} (unchanged): {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
