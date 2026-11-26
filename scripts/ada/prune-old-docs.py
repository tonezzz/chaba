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

# host-logs is ~260k+ docs across both DBs — 100-doc pages made the list
# phase alone take ~30min (0.7s/page). mddb 2.18.x caps /search limit at
# 1000 (X-Limit header; the loop below honors it), so PAGE_SIZE is now a
# request ceiling, not the page size. /delete-batch collapses the delete
# phase into single-transaction chunks.
PAGE_SIZE = 5000
DELETE_CHUNK = 1000
# /v1/search has no keyset/cursor (verified against deployed 2.15.3/2.18.10
# and upstream ≤2.19.13): offset is the only paging param, and the default
# sort is updatedAt — which reshuffles under every write, so concurrent
# bulk writes shift the offset window and stale docs get skipped
# (sweep-pagination-offset-keyset card). Three mitigations:
#   sort=key asc      — write-stable order (keys are immutable)
#   filter {ts: lt}   — server-side meta predicate (mddb ≥2.18; ignored by
#                       older servers, which fall back to the full scan +
#                       the same client-side check) so enumeration only
#                       touches expired docs instead of the whole collection
#   MAX_PASSES        — re-sweep until a pass deletes nothing, catching
#                       docs skipped by mid-sweep foreign inserts/deletes
MAX_PASSES = 5

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
         timeout: int = 60, hdrs: dict | None = None) -> object:
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if hdrs is not None:
            hdrs.update(r.headers)
        return json.loads(r.read())


def sweep(collection: str, ts_key: str, days: int, dry: bool,
          base: str = MDDB) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    t0 = time.monotonic()
    deleted, scanned, expired_seen, passes = 0, 0, 0, 0
    # server-side meta predicate — honored on mddb ≥2.18, ignored (unknown
    # JSON field) on 2.15.x, where the client-side ts check below still
    # applies to the full scan
    meta_filter = {ts_key: {"lt": cutoff}}
    for _ in range(MAX_PASSES):
        pass_start = deleted
        skip = 0
        while True:
            hdrs: dict = {}
            try:
                page = post("/search", {"collection": collection,
                                        "query": "", "limit": PAGE_SIZE,
                                        "offset": skip,
                                        "sort": "key", "asc": True,
                                        "filter": meta_filter},
                            base, hdrs=hdrs)
            except Exception as e:
                return f"{collection}: list failed — {e}"
            if not page:
                break
            # the server caps limit (X-Limit, e.g. 1000 on 2.18.x) — a short
            # page only means "done" relative to the cap, not PAGE_SIZE;
            # without this the sweep stopped after the first capped page
            try:
                xlim = hdrs.get("X-Limit") or hdrs.get("x-limit")
                eff = min(PAGE_SIZE, int(xlim or PAGE_SIZE))
            except (TypeError, ValueError):
                eff = PAGE_SIZE
            scanned += len(page)
            expired, kept = [], 0
            for d in page:
                ts = ((d.get("meta") or {}).get(ts_key) or [""])[0]
                if ts and ts < cutoff:
                    expired.append(d)
                else:
                    kept += 1
            expired_seen += len(expired)
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
            if len(page) < eff:
                break
            # deleting shifts later docs left — advance only past kept docs
            skip += kept
        passes += 1
        # dry-run counts without deleting; a pass that deleted nothing means
        # the window stayed stable — no re-sweep needed
        if dry or deleted == pass_start:
            break
    verb = "would delete" if dry else "deleted"
    host = base.split("//", 1)[-1].split("/", 1)[0]
    return (f"{collection}: expired {expired_seen}, {verb} "
            f"{deleted}/{scanned} "
            f"(>{days}d on {ts_key} @{host}, {passes} pass"
            f"{'es' if passes != 1 else ''}) "
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
