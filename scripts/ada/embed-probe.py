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
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023")
MDDB = MDDB.removesuffix("/v1").removesuffix("/")
PROBE_COLLECTION = "ada-ha-bank-general"
PROBE_QUERY = "ada memory recall probe"
EVENTS_COLLECTION = os.environ.get("ADA_OPS_COLLECTION", "ada-ha-events-tony")
STATE = os.path.expanduser("~/.local/share/ada/embed-probe.state")
REINDEX_SERVICE = os.environ.get("MDDB_REINDEX_SERVICE", "mddb-vector-reindex.service")


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


def _kick_reindex(why: str) -> None:
    """Start the reindex oneshot — non-blocking so the probe isn't killed
    by the unit's runtime budget while a full re-embed runs."""
    try:
        subprocess.run(
            ["systemctl", "--user", "start", "--no-block", REINDEX_SERVICE],
            timeout=10, check=False)
        print(f"reindex triggered ({why})")
    except Exception as exc:
        print(f"reindex trigger failed: {exc}", file=sys.stderr)


def probe() -> tuple[bool, str, int, bool]:
    """Returns (embed_path_ok, detail, index_size, index_wiped)."""
    try:
        res = _post("/v1/vector-search", {
            "collection": PROBE_COLLECTION, "query": PROBE_QUERY,
            "topK": 3, "includeContent": False}, timeout=60)
    except Exception as exc:
        return False, f"request failed: {exc}", -1, False
    if isinstance(res, dict) and res.get("error"):
        return False, str(res["error"])[:300], -1, False
    index_size = -1
    if isinstance(res, dict):
        index_size = int((res.get("searchStats") or {}).get("indexSize", -1))
    hits = res.get("results") or res.get("documents") or (
        res if isinstance(res, list) else [])
    # Embed path answered fine but the RAM index is empty — a wiped-index
    # event, not an embed outage. Distinguish so we don't page a fake
    # embed outage and so the recovery path triggers the right remediation.
    wiped = index_size == 0
    if not hits:
        if wiped:
            return True, "0 hits — index wiped (indexSize=0)", index_size, True
        return False, "vector-search returned 0 hits", index_size, False
    return True, f"{len(hits)} hits (indexSize={index_size})", index_size, wiped


def main() -> int:
    ok, detail, index_size, wiped = probe()
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
        if ok:
            # docs written during the outage had their embed jobs dropped;
            # reindex backfills them (content-hash skip keeps it cheap)
            _kick_reindex(f"recovery {prev}->up")
    else:
        print(f"{cur} (unchanged): {detail}")

    if wiped:
        # RAM index empty while docs exist — 2026-09-30 restart came up with
        # indexSize=0 despite persisted data. Reindex repopulates it.
        print("index wiped: indexSize=0 — triggering reindex")
        _emit("vector_index_wiped",
              f"vector-search healthy but {PROBE_COLLECTION} indexSize=0 — reindex triggered")
        _kick_reindex("indexSize=0")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
