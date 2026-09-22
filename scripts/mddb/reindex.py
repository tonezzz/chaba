#!/usr/bin/env python3
"""Reindex (re-embed) MDDB collections after an embedding model/provider
change.

Calls /v1/vector-reindex per collection — the only endpoint that
regenerates vectors. NOTE: re-adding docs via /v1/add does NOT re-embed
existing docs (content dedup); this script exists because that mistake
left pre-alias embeddings unreachable (2026-09-22: ada-ha-bank-* docs
scored ~0.02 until force-reindexed).

The endpoint is synchronous and slow (~15s/doc through the embedding
proxy), so per-doc progress is not available — it reports
{embedded, skipped, failed} when done.

Usage:
    python3 scripts/mddb/reindex.py                        # default set
    python3 scripts/mddb/reindex.py --collection test --collection kb-system
    python3 scripts/mddb/reindex.py --dry-run              # list counts only
    MDDB_BASE=http://100.74.146.0:11023 python3 scripts/mddb/reindex.py
"""
import argparse
import json
import os
import urllib.request

MDDB_BASE = os.environ.get("MDDB_BASE", "http://100.74.146.0:11023")
COLLECTIONS = [c for c in os.environ.get("COLLECTIONS", "").split(",") if c]

DEFAULT_COLLECTIONS = [
    "chaba-architecture",
    "infrastructure-ssot",
    "kb-development",
    "kb-features",
    "kb-operations",
    "kb-system",
    "test",
]

REINDEX_TIMEOUT = int(os.environ.get("REINDEX_TIMEOUT", "900"))


def req_post(path, payload, timeout=30):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{MDDB_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def doc_count(collection):
    payload = {"collection": collection, "query": "", "limit": 1}
    try:
        page = req_post("/v1/search", payload)
    except Exception as e:
        print(f"- {collection}: list failed: {e}")
        return None
    # /v1/search has no total; just report whether it's non-empty
    return len(page)


def main():
    parser = argparse.ArgumentParser(description="Re-embed MDDB collections")
    parser.add_argument("--dry-run", action="store_true",
                        help="List target collections without reindexing")
    parser.add_argument("--collection", action="append",
                        help="Reindex a specific collection only (repeatable)")
    parser.add_argument("--no-force", action="store_true",
                        help="Skip docs that already have vectors "
                             "(default: force re-embed all)")
    args = parser.parse_args()

    collections = args.collection or COLLECTIONS or DEFAULT_COLLECTIONS
    print(f"MDDB base: {MDDB_BASE}")
    print(f"Collections: {', '.join(collections)}")
    if args.dry_run:
        print("DRY RUN")
        return

    failed = []
    for coll in collections:
        print(f"Reindexing {coll} (this takes ~15s/doc, synchronous)...",
              flush=True)
        try:
            r = req_post("/v1/vector-reindex",
                         {"collection": coll, "force": not args.no_force},
                         timeout=REINDEX_TIMEOUT)
            print(f"  -> embedded={r.get('embedded')} "
                  f"skipped={r.get('skipped')} failed={r.get('failed')}"
                  + (f" errors={r.get('errors')}" if r.get("errors") else ""))
            if r.get("failed"):
                failed.append(coll)
        except Exception as e:
            print(f"  !! {coll}: {e} (server may still be processing)")
            failed.append(coll)
    print("FAILED:", ", ".join(failed) if failed else "none")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
