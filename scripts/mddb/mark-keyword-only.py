#!/usr/bin/env python3
"""Declare meta-only MDDB docs keyword-only (search_mode=keyword meta).

Card mddb-cms-11027-embed-coverage-gap-250-do-e35321 — Tony approved
option A (declare keyword-only) 2026-11-25. Docs-sync/SSOT pointer
stubs have empty contentMd by design (content lives in the git repos);
they can never embed, so an embedded_documents < total_documents delta
on their collections is EXPECTED, not a coverage gap. Stamping
meta.search_mode=["keyword"] makes the declaration machine-readable:
consumers and gap-analysis scripts can tell intentional keyword-only
docs apart from docs whose embed jobs were dropped.

Docs are found by empty contentMd — the same condition /v1/vector-reindex
uses to skip them. Meta is updated via PATCH /v1/update (content
untouched, no re-embed, one revision per changed doc).

Usage:
    python3 scripts/mddb/mark-keyword-only.py                    # all collections
    python3 scripts/mddb/mark-keyword-only.py --collection devin-kb chaba-archive
    python3 scripts/mddb/mark-keyword-only.py --dry-run

Env:
    MDDB_BASE  default http://100.102.134.91:11027 (CMS plane)
"""
import argparse
import json
import os
import sys
import urllib.request

MDDB = os.environ.get("MDDB_BASE", "http://100.102.134.91:11027").rstrip("/")
MARK = "search_mode"
MARK_VALUE = "keyword"


def req(method, path, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(MDDB + path, data=data,
                               headers={"content-type": "application/json"},
                               method=method)
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())


def list_docs(collection):
    docs, off = [], 0
    while True:
        page = req("POST", "/v1/search",
                   {"collection": collection, "query": "",
                    "limit": 100, "offset": off})
        if not page:
            return docs
        docs += page
        if len(page) < 100:
            return docs
        off += 100


def collections():
    return [c["name"] for c in
            (req("GET", "/v1/stats").get("collections") or [])]


def is_marked(meta):
    v = (meta or {}).get(MARK) or []
    return MARK_VALUE in v


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collection", action="append",
                    help="limit to named collection(s); default = all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    colls = args.collection or collections()
    stats = {"scanned": 0, "meta_only": 0, "marked": 0, "already": 0}
    for coll in colls:
        try:
            docs = list_docs(coll)
        except Exception as exc:
            print(f"{coll}: list failed: {exc}", file=sys.stderr)
            continue
        n_mark = 0
        for d in docs:
            stats["scanned"] += 1
            if (d.get("contentMd") or "").strip():
                continue
            stats["meta_only"] += 1
            if is_marked(d.get("meta")):
                stats["already"] += 1
                continue
            if args.dry_run:
                n_mark += 1
                continue
            meta = dict(d.get("meta") or {})
            meta[MARK] = [MARK_VALUE]
            try:
                req("PATCH", "/v1/update",
                    {"collection": coll, "key": d["key"],
                     "lang": d.get("lang", "en"), "meta": meta})
                n_mark += 1
                stats["marked"] += 1
            except Exception as exc:
                print(f"{coll}/{d['key']}: mark failed: {exc}",
                      file=sys.stderr)
        if n_mark:
            print(f"{coll}: {'would mark' if args.dry_run else 'marked'} "
                  f"{n_mark} meta-only doc(s)")
    would = stats["meta_only"] - stats["already"] - stats["marked"] \
        if args.dry_run else 0
    print(f"done: scanned={stats['scanned']} meta_only={stats['meta_only']} "
          f"marked={stats['marked']} already={stats['already']}"
          + (f" would_mark={would}" if args.dry_run else "")
          + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
