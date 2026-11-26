#!/usr/bin/env python3
"""device-telemetry prune — retention sweep for beacon history keys.

Deletes <dev>/<unix-ts> docs older than the retention window from the MDDB
device-telemetry collection. Never touches <dev>/latest (always-current
read) or _watch/<dev> docs (armed lost-mode watches — not history).
Nightly on idc03 via ssot.jobs.yml (job:device-telemetry-prune).

  prune.py             # sweep
  prune.py --dry-run   # count only

Env:
  DEVICE_TELEMETRY_MDBB            default http://100.102.134.91:11026/v1
  DEVICE_TELEMETRY_RETENTION_DAYS  default 7 (HA logbook covers long range)
"""
import json
import os
import sys
import time
import urllib.request

MDBB = os.environ.get("DEVICE_TELEMETRY_MDBB",
                      "http://100.102.134.91:11026/v1").rstrip("/")
DAYS = int(os.environ.get("DEVICE_TELEMETRY_RETENTION_DAYS", "7"))
COLLECTION = "device-telemetry"
PAGE = 5000
# 1000-doc delete batches took >120s on mddb-ops under load (2026-11-26,
# timer-alert-idc03-device-telemetry-prune) and the client timed out mid-
# sweep. Smaller chunks keep each write well inside the server's 120s
# window; the job timeout was raised to 30m for the extra round trips.
CHUNK = 100
# /v1/search has no keyset/cursor (verified against deployed 2.15.3/2.18.10
# and upstream <=2.19.13): offset is the only paging param, and the default
# sort is updatedAt — which reshuffles under every write, so concurrent
# beacon writes shift the offset window and stale docs get skipped
# (sweep-pagination-offset-keyset card). sort=key pins a write-stable
# order; MAX_PASSES re-sweeps until a pass deletes nothing; the expiry
# predicate stays client-side on the doc key because meta filters cannot
# express "key ends with /<old-epoch>" nor exclude */latest and _watch/*.
MAX_PASSES = 5


def _post(path: str, body: dict, timeout: int = 300,
          hdrs: dict | None = None) -> object:
    req = urllib.request.Request(
        f"{MDBB}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if hdrs is not None:
            hdrs.update(r.headers)
        return json.loads(r.read())


def _expired(key: str, cutoff: int) -> bool:
    dev, _, ts = key.rpartition("/")
    return not dev.startswith("_watch") and ts.isdigit() and int(ts) < cutoff


def main() -> int:
    dry = "--dry-run" in sys.argv
    cutoff = int(time.time()) - DAYS * 86400
    deleted, scanned, expired, passes = 0, 0, 0, 0
    for _ in range(MAX_PASSES):
        pass_start = deleted
        skip = 0
        while True:
            hdrs: dict = {}
            page = _post("/search", {"collection": COLLECTION, "query": "",
                                     "limit": PAGE, "offset": skip,
                                     "sort": "key", "asc": True},
                         hdrs=hdrs)
            if not page:
                break
            # the server caps limit (X-Limit, e.g. 1000 on 2.18.x) — a short
            # page only means "done" relative to the cap, not PAGE
            try:
                xlim = hdrs.get("X-Limit") or hdrs.get("x-limit")
                eff = min(PAGE, int(xlim or PAGE))
            except (TypeError, ValueError):
                eff = PAGE
            scanned += len(page)
            old = [d for d in page if _expired(d["key"], cutoff)]
            expired += len(old)
            kept = len(page) - len(old)
            if dry:
                deleted += len(old)
                kept += len(old)
            else:
                for i in range(0, len(old), CHUNK):
                    chunk = old[i:i + CHUNK]
                    n = _post("/delete-batch", {
                        "collection": COLLECTION,
                        "documents": [{"key": d["key"],
                                       "lang": d.get("lang", "en")}
                                      for d in chunk]}).get("deleted", 0)
                    deleted += n
                    kept += len(chunk) - n
            if len(page) < eff:
                break
            # deleting shifts later docs left — advance only past kept docs
            skip += kept
        passes += 1
        if dry or deleted == pass_start:
            break
    verb = "would delete" if dry else "deleted"
    print(f"{COLLECTION}: expired {expired}, {verb} {deleted}/{scanned} "
          f"(>{DAYS}d on key ts, {passes} pass"
          f"{'es' if passes != 1 else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
