#!/usr/bin/env python3
"""prune-old-docs.py — retention sweep for append-only MDDB collections.

Deletes docs whose timestamp meta is older than the collection's retention
window. Append-only collections grow forever otherwise — this is the
standing rule, run inside the export-transcripts refresh chain.

Retention policy (days):
  host-logs               3   journald shipper — high-volume noise;
                              14d ≈ 530k docs > the ~250k /v1/search
                              paging limit, which broke enumeration and
                              silently disabled this sweep (MEM-0871,
                              2026-11-07). 3d ≈ 114k keeps it listable.
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
# ada-ha-* telemetry lives on a DIFFERENT ops store — mddb-ops on idc02
# (docs/kb/mddb-ops-split.md). Distinct env name so a host-logs
# MDDB_OPS_URL pin can't misroute the ada sweep.
ADA_OPS_MDB = os.environ.get("MDDB_ADA_OPS_URL",
                             "http://100.123.163.11:11025/v1").rstrip("/")

# host-logs is ~260k docs across both DBs — 100-doc pages made the list
# phase alone take ~30min (0.7s/page). The server caps /v1/search pages
# at 1000 docs regardless of the requested limit, so PAGE_SIZE is the
# effective page.
PAGE_SIZE = 1000
DELETE_CHUNK = 1000

# collection -> (timestamp meta key, retention days)
POLICY = {"host-logs": ("ts", 3)}
ADA_INSTANCES = ("tony", "michael", "kk", "chaba", "dev",
                 "kk-dev", "tony-dev")
for _inst in ADA_INSTANCES:
    POLICY[f"ada-ha-events-{_inst}"] = ("period_end", 30)
    POLICY[f"ada-ha-snapshots-{_inst}"] = ("refreshed_at", 30)
# collections served from an ops DB instead of the leader — host-logs
# on idc03 :11026, ada-ha-* telemetry on idc02 :11025 (the mddb-ops
# split moved them; the leader copies are frozen residue — sweeping
# them is harmless but pointless, the live copies grow there).
COLLECTION_BASE = {"host-logs": OPS_MDB}
ADA_BASES = (ADA_OPS_MDB, MDDB)


def collection_bases(collection: str) -> list[str]:
    if collection.startswith("ada-ha-"):
        return list(ADA_BASES)
    return [COLLECTION_BASE.get(collection, MDDB)]


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
        # Server-side meta filter is load-bearing: an unfiltered scan
        # of a ~660k-doc collection blows the ~50s request deadline
        # and the whole sweep deletes 0 (observed 2026-11-23..25 on
        # mddb-ops host-logs). With the filter, only expired docs are
        # returned — typically ~1 day of churn — and offsets stay
        # near zero because kept≈0. Even filtered, a page can exceed
        # the server's ~30s write timeout when the host is loaded, so
        # retry a few times before giving up on the sweep.
        page = None
        for attempt in range(4):
            try:
                page = post("/search", {"collection": collection,
                                        "query": "",
                                        "limit": PAGE_SIZE,
                                        "offset": skip,
                                        "filter": {ts_key: {"lt": cutoff}}},
                            base)
                break
            except Exception as e:
                if attempt == 3:
                    return f"{collection}: list failed — {e}"
                time.sleep(15 * (attempt + 1))
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
    host = base.split("//", 1)[-1].split("/", 1)[0]
    return (f"{collection}: {verb} {deleted}/{scanned} "
            f"(>{days}d on {ts_key} @{host}) "
            f"in {time.monotonic() - t0:.0f}s")


def main() -> int:
    dry = "--dry-run" in sys.argv
    only = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        if i + 1 < len(sys.argv):
            only = sys.argv[i + 1]
    for coll, (ts_key, days) in POLICY.items():
        if only and only not in coll:
            continue
        for base in collection_bases(coll):
            print(sweep(coll, ts_key, days, dry, base))
    if only is None:
        # one-shot leader cleanup: host-logs migrated to the ops DB — the
        # stale leader copy still ages out on its own 14d window
        print(sweep("host-logs", "ts", 14, dry, MDDB))
    return 0


if __name__ == "__main__":
    sys.exit(main())
