#!/usr/bin/env python3
"""Re-embed every mddb collection so the in-memory vector index is repopulated.

mddb loads its RAM vector index from the persisted `vectors` bucket at
startup — but any doc whose embedding was dropped (provider outage, queue
overflow, crash before flush) leaves the index incomplete, and plain
restarts have been observed to come up with `indexSize=0` even though
documents exist (2026-09-30). vector-reindex skips docs whose stored
content-hash already matches, so a full sweep is cheap once vectors are
healthy: the cost is one embedding call per missing/changed chunk.

Trigger paths:
  - mddb.container ExecStartPost (every start; skips already-embedded docs)
  - mddb-embed-probe.service when it sees indexSize≈0 or a down→up recovery

Writes one ops-event doc to ada-ha-events-tony at the end.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023")
MDDB = MDDB.removesuffix("/v1").removesuffix("/")
EVENTS_COLLECTION = os.environ.get("ADA_OPS_COLLECTION", "ada-ha-events-tony")
HEALTH_DEADLINE_S = int(os.environ.get("MDDB_REINDEX_HEALTH_WAIT", "300"))
PER_COLLECTION_TIMEOUT_S = int(os.environ.get("MDDB_REINDEX_TIMEOUT", "600"))


def _post(path: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        MDDB + path, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _get(path: str, timeout: int = 30) -> dict:
    return json.loads(urllib.request.urlopen(MDDB + path, timeout=timeout).read())


def _emit(ev_type: str, detail: str) -> None:
    now = datetime.now(timezone.utc).astimezone()
    try:
        _post("/v1/add", {
            "collection": EVENTS_COLLECTION,
            "key": f"ops-vector-reindex-{ev_type}-{now:%Y%m%d%H%M%S}",
            "lang": "en", "contentMd": detail,
            "meta": {"kind": ["ops-event"], "type": [ev_type],
                     "instance": ["tony"], "session_id": ["vector-reindex"],
                     "ts": [now.isoformat(timespec="seconds")]},
        })
    except Exception as exc:
        print(f"ops event write failed: {exc}", file=sys.stderr)


def _wait_healthy() -> bool:
    deadline = time.time() + HEALTH_DEADLINE_S
    while time.time() < deadline:
        try:
            if _get("/v1/health", timeout=5).get("status") == "healthy":
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def main() -> int:
    if not _wait_healthy():
        print("mddb never became healthy — aborting reindex", file=sys.stderr)
        return 1
    collections = [c["name"] for c in (_get("/v1/stats").get("collections") or [])]
    print(f"reindexing {len(collections)} collections")
    tot = {"embedded": 0, "skipped": 0, "failed": 0}
    bad = []
    for name in collections:
        try:
            r = _post("/v1/vector-reindex", {"collection": name},
                      timeout=PER_COLLECTION_TIMEOUT_S)
            for k in tot:
                tot[k] += int(r.get(k) or 0)
            if r.get("failed"):
                bad.append(f"{name}:{r['failed']}")
            print(f"  {name}: embedded={r.get('embedded',0)} "
                  f"skipped={r.get('skipped',0)} failed={r.get('failed',0)}")
        except Exception as exc:
            bad.append(f"{name}: {exc}")
            print(f"  {name}: ERROR {exc}", file=sys.stderr)
    detail = (f"vector-reindex complete — embedded={tot['embedded']} "
              f"skipped={tot['skipped']} failed={tot['failed']}"
              + (f" | failures: {', '.join(bad)[:400]}" if bad else ""))
    print(detail)
    _emit("vector_reindex", detail)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
