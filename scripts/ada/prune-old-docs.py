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
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

MDDB = "http://100.74.146.0:11023/v1"

# collection -> (timestamp meta key, retention days)
POLICY = {
    "host-logs": ("ts", 14),
    "ada-ha-events-tony": ("period_end", 30),
    "ada-ha-events-michael": ("period_end", 30),
    "ada-ha-snapshots-tony": ("refreshed_at", 30),
    "ada-ha-snapshots-michael": ("refreshed_at", 30),
}


def post(path: str, body: dict) -> object:
    req = urllib.request.Request(
        f"{MDDB}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def sweep(collection: str, ts_key: str, days: int, dry: bool) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    skip, deleted, scanned = 0, 0, 0
    while True:
        try:
            page = post("/search", {"collection": collection, "query": "",
                                    "limit": 100, "offset": skip})
        except Exception as e:
            return f"{collection}: list failed — {e}"
        if not page:
            break
        scanned += len(page)
        kept = 0
        for d in page:
            ts = ((d.get("meta") or {}).get(ts_key) or [""])[0]
            if ts and ts < cutoff:
                if dry:
                    deleted += 1
                    kept += 1
                else:
                    try:
                        post("/delete", {"collection": collection,
                                         "key": d["key"],
                                         "lang": d.get("lang", "en")})
                        deleted += 1
                    except urllib.error.HTTPError:
                        kept += 1
            else:
                kept += 1
        if len(page) < 100:
            break
        # deleting shifts later docs left — advance only past kept docs
        skip += kept
    verb = "would delete" if dry else "deleted"
    return f"{collection}: {verb} {deleted}/{scanned} (>{days}d on {ts_key})"


def main() -> int:
    dry = "--dry-run" in sys.argv
    for coll, (ts_key, days) in POLICY.items():
        print(sweep(coll, ts_key, days, dry))
    return 0


if __name__ == "__main__":
    sys.exit(main())
