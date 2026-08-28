#!/usr/bin/env python3
"""Reindex all MDDB collections after an embedding model/provider change.

Reads every document from /v1/search and re-adds it through /v1/add so the
configured embedding provider regenerates vectors. Safe to re-run because it
preserves existing keys and metadata.

Usage:
    MDDB_BASE=http://tony-dell:11023 python3 scripts/mddb/reindex.py
    MDDB_BASE=http://localhost:11023 COLLECTIONS=test,kb-system python3 scripts/mddb/reindex.py
    python3 scripts/mddb/reindex.py --dry-run
"""
import argparse
import json
import os
import urllib.request
import urllib.error

MDDB_BASE = os.environ.get("MDDB_BASE", "http://tony-dell:11023")
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


def req_post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{MDDB_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def list_docs(collection):
    docs = []
    skip = 0
    while True:
        payload = {"collection": collection, "query": "", "limit": 100, "offset": skip}
        page = req_post("/v1/search", payload)
        if not page:
            break
        docs.extend(page)
        if len(page) < 100:
            break
        skip += 100
    return docs


def reindex_doc(collection, doc, dry_run=False):
    key = doc["key"]
    lang = doc.get("lang", "en_US")
    content = doc.get("contentMd")
    meta = doc.get("meta") or {}
    if not content:
        print(f"  skip {key}: no content")
        return False
    if dry_run:
        print(f"  [dry-run] would reindex {key}")
        return True
    payload = {
        "collection": collection,
        "key": key,
        "lang": lang,
        "contentMd": content,
        "meta": meta,
    }
    req_post("/v1/add", payload)
    return True


def main():
    parser = argparse.ArgumentParser(description="Reindex MDDB collections")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be reindexed without writing",
    )
    parser.add_argument(
        "--collection",
        action="append",
        help="Reindex a specific collection only (can repeat)",
    )
    args = parser.parse_args()

    collections = args.collection or COLLECTIONS or DEFAULT_COLLECTIONS
    print(f"MDDB base: {MDDB_BASE}")
    print(f"Collections to reindex: {', '.join(collections)}")
    if args.dry_run:
        print("DRY RUN: no documents will be written")

    total_source = 0
    total_updated = 0
    for collection in collections:
        print(f"Listing collection: {collection}")
        docs = list_docs(collection)
        count = len(docs)
        print(f"- Found {count} documents")
        total_source += count
        for i, d in enumerate(docs):
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{count} done")
            if reindex_doc(collection, d, dry_run=args.dry_run):
                total_updated += 1
    print(f"Reindexed {total_updated} of {total_source} documents")


if __name__ == "__main__":
    main()
