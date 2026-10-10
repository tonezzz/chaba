#!/usr/bin/env python3
"""device-telemetry prune — retention sweep for beacon history keys.

Deletes <dev>/<unix-ts> docs older than the retention window from the MDDB
device-telemetry collection. Never touches <dev>/latest (always-current
read) or _watch/<dev> docs (armed lost-mode watches — not history).
Nightly on idc03 via ssot.jobs.yml (job:device-telemetry-prune).

  prune.py             # sweep
  prune.py --dry-run   # count only

Env:
  DEVICE_TELEMETRY_MDBB            default http://100.102.134.91:11023/v1
  DEVICE_TELEMETRY_RETENTION_DAYS  default 7 (HA logbook covers long range)
"""
import json
import os
import sys
import time
import urllib.request

MDBB = os.environ.get("DEVICE_TELEMETRY_MDBB",
                      "http://100.102.134.91:11023/v1").rstrip("/")
DAYS = int(os.environ.get("DEVICE_TELEMETRY_RETENTION_DAYS", "7"))
COLLECTION = "device-telemetry"
PAGE = 5000
CHUNK = 1000


def _post(path: str, body: dict, timeout: int = 120) -> object:
    req = urllib.request.Request(
        f"{MDBB}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _expired(key: str, cutoff: int) -> bool:
    dev, _, ts = key.rpartition("/")
    return not dev.startswith("_watch") and ts.isdigit() and int(ts) < cutoff


def main() -> int:
    dry = "--dry-run" in sys.argv
    cutoff = int(time.time()) - DAYS * 86400
    skip, deleted, scanned = 0, 0, 0
    while True:
        page = _post("/search", {"collection": COLLECTION, "query": "",
                                 "limit": PAGE, "offset": skip})
        if not page:
            break
        scanned += len(page)
        old = [d for d in page if _expired(d["key"], cutoff)]
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
        if len(page) < PAGE:
            break
        # deleting shifts later docs left — advance only past kept docs
        skip += kept
    verb = "would delete" if dry else "deleted"
    print(f"{COLLECTION}: {verb} {deleted}/{scanned} (>{DAYS}d on key ts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
