#!/usr/bin/env python3
"""Sync docs/kb markdown files to MDDB kb-* collections for semantic search.

Canonical scheme: collection = kb-<mapped category> from the file's
`category:` frontmatter. Keys are the KB filenames. Re-homes documents that
ended up in non-canonical collections (e.g. auto-kb's old chaba-* targets)
and detects content drift via a stored md5.

Usage:
    python3 scripts/sync-kb-to-mddb.py                # full sync
    python3 scripts/sync-kb-to-mddb.py --dry-run      # plan only, no writes
    python3 scripts/sync-kb-to-mddb.py --missing-only # only add absent keys
    python3 scripts/sync-kb-to-mddb.py --sync-deletes # also remove orphans

Env:
    MDDB_BASE   default http://100.74.146.0:11023 (idc01, tailnet-only)
    KB_DIR      default <repo>/docs/kb
"""
import argparse
import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = Path(os.environ.get("KB_DIR", REPO_ROOT / "docs" / "kb"))
MDDB_BASE = os.environ.get("MDDB_BASE", "http://100.74.146.0:11023")

# Collections that hold KB documents (kb-* canonical; chaba-* are legacy
# auto-kb targets whose KB docs get re-homed). chaba-architecture is NOT
# here on purpose: it holds architecture docs that are not KB files.
KB_COLLECTIONS = [
    "kb-development",
    "kb-features",
    "kb-operations",
    "kb-system",
    "chaba-development",
    "chaba-system",
]

CATEGORY_MAP = {
    "troubleshooting": "kb-development",
    "development": "kb-development",
    "operations": "kb-operations",
    "architecture": "kb-system",
    "implementation": "kb-system",
}
DEFAULT_COLLECTION = "kb-features"

_session = requests.Session()
_retry = Retry(total=5, backoff_factor=0.5,
               status_forcelist=[429, 500, 502, 503, 504])
_session.mount("http://", HTTPAdapter(max_retries=_retry))
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def meta_first(meta, name):
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""


def parse_frontmatter(text):
    """Return (category, title) from a KB markdown file."""
    category = ""
    m = re.search(r"^category:\s*(.+)$", text, re.MULTILINE)
    if m:
        category = m.group(1).strip()
    t = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = t.group(1).strip() if t else ""
    return category, title


def collection_for(category):
    return CATEGORY_MAP.get(category, DEFAULT_COLLECTION)


def list_docs(collection):
    """Page through /v1/search to list {key, lang, meta} for a collection."""
    docs = {}
    skip = 0
    while True:
        resp = _session.post(
            f"{MDDB_BASE}/v1/search",
            json={"collection": collection, "query": "", "limit": 100, "offset": skip},
            timeout=30,
        )
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        for d in page:
            docs[d["key"]] = {"lang": d.get("lang", "en"), "meta": d.get("meta") or {}}
        if len(page) < 100:
            break
        skip += 100
    return docs


def add_doc(collection, key, content_md, meta):
    meta_arrays = {k: [str(v)] for k, v in meta.items()}
    resp = _session.post(
        f"{MDDB_BASE}/v1/add",
        json={"collection": collection, "key": key, "lang": "en",
              "contentMd": content_md, "meta": meta_arrays},
        timeout=60,
    )
    resp.raise_for_status()


def delete_doc(collection, key, lang):
    resp = _session.post(
        f"{MDDB_BASE}/v1/delete",
        json={"collection": collection, "key": key, "lang": lang},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description="Sync docs/kb to MDDB")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--missing-only", action="store_true",
                        help="Only add keys absent from every KB collection")
    parser.add_argument("--sync-deletes", action="store_true",
                        help="Delete MDDB docs whose KB file no longer exists")
    args = parser.parse_args()

    files = sorted(p for p in KB_DIR.glob("*.md") if p.name != "README.md")
    print(f"KB dir: {KB_DIR} ({len(files)} files)")
    print(f"MDDB:   {MDDB_BASE}")

    # Build key -> {collection: {lang, meta}} index
    index = {}
    for coll in KB_COLLECTIONS:
        try:
            for key, info in list_docs(coll).items():
                index.setdefault(key, {})[coll] = info
        except Exception as e:
            print(f"warn: cannot list {coll}: {e}")

    seen_keys = set()
    stats = {"added": 0, "updated": 0, "moved": 0, "skipped": 0, "orphans": 0}

    for path in files:
        key = path.name
        seen_keys.add(key)
        text = path.read_text(encoding="utf-8")
        category, title = parse_frontmatter(text)
        target = collection_for(category)
        md5 = hashlib.md5(text.encode()).hexdigest()
        present = index.get(key, {})

        def do_add():
            add_doc(target, key, text, {
                "title": title or key,
                "source": "kb",
                "rel_path": f"docs/kb/{key}",
                "category": category or "uncategorized",
                "content_md5": md5,
                "last_synced": datetime.now().isoformat(),
            })

        if target not in present:
            label = "MOVE->ADD" if present else "ADD"
            print(f"  {label} {key} -> {target}"
                  + (f" (from {', '.join(present)})" if present else ""))
            if not args.dry_run:
                do_add()
            stats["moved" if present else "added"] += 1
            if present and not args.missing_only:
                for coll, info in present.items():
                    print(f"  DEL  {key} from {coll}")
                    if not args.dry_run:
                        delete_doc(coll, key, info["lang"])
        else:
            existing_md5 = meta_first(present[target]["meta"], "content_md5")
            if args.missing_only or existing_md5 == md5:
                stats["skipped"] += 1
                continue
            print(f"  UPD  {key} in {target}")
            if not args.dry_run:
                do_add()
            stats["updated"] += 1
            extra = [c for c in present if c != target]
            for coll in extra:
                print(f"  DEL  {key} from {coll} (duplicate)")
                if not args.dry_run:
                    delete_doc(coll, key, present[coll]["lang"])

    orphans = sorted(set(index) - seen_keys)
    for key in orphans:
        stats["orphans"] += 1
        colls = index[key]
        print(f"  ORPHAN {key} in {', '.join(colls)} (no file on disk)")
        if args.sync_deletes:
            for coll, info in colls.items():
                print(f"  DEL  {key} from {coll}")
                if not args.dry_run:
                    delete_doc(coll, key, info["lang"])

    print("\nDone." + (" (dry-run)" if args.dry_run else ""))
    print(f"  added={stats['added']} updated={stats['updated']} "
          f"moved={stats['moved']} unchanged={stats['skipped']} "
          f"orphans={stats['orphans']}")
    if orphans and not args.sync_deletes:
        print("  re-run with --sync-deletes to remove orphans")


if __name__ == "__main__":
    sys.exit(main())
