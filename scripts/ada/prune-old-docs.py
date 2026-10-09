#!/usr/bin/env python3
"""prune-old-docs.py — retention sweep for append-only MDDB collections.

Deletes docs whose timestamp meta is older than the collection's retention
window. Append-only collections grow forever otherwise — this is the
standing rule, run inside the export-transcripts refresh chain.

Retention policy (days):
  host-logs              14   journald shipper — high-volume noise
  ada-ha-events-*        30   HA event bundles — superseded by newer bundles
  ada-ha-snapshots-*     30   HA state snapshots — same

Deliberately NOT pruned: ada-ha-scenario-reports and ops-digests are
authored artifacts (each doc is a report), and every ada-ha-bank-* /
kb-* / chaba-* / cms collection is bounded by maxRevisions instead.

  prune-old-docs.py             # sweep all collections in the policy
  prune-old-docs.py --dry-run   # count what would be deleted
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

MDDB = "http://100.102.134.91:11023/v1"
# ops telemetry lives on the no-embed ops DB (ssot.log-digest-standard)
OPS_MDB = os.environ.get("MDDB_OPS_URL",
                         "http://100.102.134.91:11026/v1").rstrip("/")

# host-logs is ~260k docs across both DBs — 100-doc pages made the list
# phase alone take ~30min (0.7s/page). 5000-doc pages stay ~1s even at
# deep offsets, and /delete-batch collapses the delete phase likewise.
PAGE_SIZE = 5000
DELETE_CHUNK = 1000

# collection -> (timestamp meta key, retention days)
POLICY = {
    "host-logs": ("ts", 14),
    "ada-ha-events-tony": ("period_end", 30),
    "ada-ha-events-michael": ("period_end", 30),
    "ada-ha-snapshots-tony": ("refreshed_at", 30),
    "ada-ha-snapshots-michael": ("refreshed_at", 30),
}
# collections served from the ops DB instead of the leader
OPS_COLLECTIONS = {"host-logs"}


def post(path: str, body: dict, base: str = MDDB,
         timeout: int = 60) -> object:
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def sweep(collection: str, ts_key: str, days: int, dry: bool,
          base: str = MDDB) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    t0 = time.monotonic()
    skip, deleted, scanned = 0, 0, 0
    while True:
        try:
            page = post("/search", {"collection": collection, "query": "",
                                    "limit": PAGE_SIZE, "offset": skip},
                        base)
        except Exception as e:
            return f"{collection}: list failed — {e}"
        if not page:
            break
        scanned += len(page)
        expired, kept = [], 0
        for d in page:
            ts = ((d.get("meta") or {}).get(ts_key) or [""])[0]
            if ts and ts < cutoff:
                expired.append(d)
            else:
                kept += 1
        if dry:
            deleted += len(expired)
            kept += len(expired)
        else:
            for i in range(0, len(expired), DELETE_CHUNK):
                chunk = expired[i:i + DELETE_CHUNK]
                try:
                    r = post("/delete-batch",
                             {"collection": collection,
                              "documents": [{"key": d["key"],
                                             "lang": d.get("lang", "en")}
                                            for d in chunk]},
                             base, timeout=180)
                    deleted += r.get("deleted", 0)
                    kept += len(chunk) - r.get("deleted", 0)
                except Exception:
                    kept += len(chunk)
        if len(page) < PAGE_SIZE:
            break
        # deleting shifts later docs left — advance only past kept docs
        skip += kept
    verb = "would delete" if dry else "deleted"
    return (f"{collection}: {verb} {deleted}/{scanned} "
            f"(>{days}d on {ts_key}) in {time.monotonic() - t0:.0f}s")


def main() -> int:
    dry = "--dry-run" in sys.argv
    for coll, (ts_key, days) in POLICY.items():
        base = OPS_MDB if coll in OPS_COLLECTIONS else MDDB
        print(sweep(coll, ts_key, days, dry, base))
    # one-shot leader cleanup: host-logs migrated to the ops DB — the
    # stale leader copy still ages out on its own 14d window
    print(sweep("host-logs", "ts", 14, dry, MDDB))
    return 0


if __name__ == "__main__":
    sys.exit(main())
