#!/usr/bin/env python3
"""Sync arbitrary markdown doc trees to MDDB collections for Ada recall.

Companion to sync-kb-to-mddb.py (docs/kb -> kb-*) and sync-ssot-to-mddb.py
(docs/ssot -> infrastructure-ssot). This script covers the rest: whole doc
repos like devin-kb, and the chaba docs/ subdirs that have no pipeline.

Each source maps a directory tree to one collection. Keys are repo-relative
paths, so `docs/runbooks/foo.md` -> key `runbooks/foo.md`. Drift detection
via content_md5 meta — unchanged files are skipped; orphans are reported
(and removed with --sync-deletes).

Sources must be reachable locally — run this on the host that holds the
checkout (devin-kb: tony-dell, mn01; chaba docs: any chaba clone).

Usage:
    python3 scripts/sync-docs-to-mddb.py                # full sync
    python3 scripts/sync-docs-to-mddb.py --dry-run      # plan only
    python3 scripts/sync-docs-to-mddb.py --missing-only # only add absent keys
    python3 scripts/sync-docs-to-mddb.py --sync-deletes # also remove orphans
    python3 scripts/sync-docs-to-mddb.py --source devin-kb  # one source only

Env:
    MDDB_BASE    default http://100.74.146.0:11023 (idc01, tailnet-only)
    DEVIN_KB_DIR default ~/devin-kb/docs
"""
import argparse
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO_ROOT = Path(__file__).resolve().parent.parent
MDDB_BASE = os.environ.get("MDDB_BASE", "http://100.74.146.0:11023")

# Docs trees that have their own pipelines or must never be synced here.
_EXCLUDED_CHABA_DIRS = {
    "kb",             # sync-kb-to-mddb.py
    "ssot",           # sync-ssot-to-mddb.py
    "ada-memory",     # sync-ada-memory-to-mddb.py (vault authoring tier)
    "archive",        # superseded material
    "backups",        # dumped data, not documentation
    "ssot-summaries", # generated artifacts
}

SOURCES = [
    {
        "name": "devin-kb",
        "dir": Path(os.environ.get(
            "DEVIN_KB_DIR", Path.home() / "devin-kb" / "docs")),
        "collection": "devin-kb",
        "recursive": True,
        "skip_names": {"README.md"},
    },
    {
        "name": "chaba-docs",
        "dir": REPO_ROOT / "docs",
        "collection": "chaba-docs",
        "recursive": True,
        "exclude_dirs": _EXCLUDED_CHABA_DIRS,
        "skip_names": {"README.md"},
    },
    {
        "name": "chaba-archive",
        "dir": REPO_ROOT / "docs" / "kb" / "archive",
        "collection": "chaba-archive",
        "recursive": True,
        "skip_names": set(),
    },
]

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


def list_docs(collection):
    docs = {}
    skip = 0
    while True:
        resp = _session.post(
            f"{MDDB_BASE}/v1/search",
            json={"collection": collection, "query": "", "limit": 100,
                  "offset": skip},
            timeout=30,
        )
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        for d in page:
            docs[d["key"]] = {"lang": d.get("lang", "en"),
                              "meta": d.get("meta") or {}}
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
        timeout=120,  # first add embeds inline; big docs embed slowly
    )
    resp.raise_for_status()


def delete_doc(collection, key, lang):
    resp = _session.post(
        f"{MDDB_BASE}/v1/delete",
        json={"collection": collection, "key": key, "lang": lang},
        timeout=30,
    )
    resp.raise_for_status()


def iter_files(source):
    """Yield (key, path) for a source's markdown files."""
    root = source["dir"]
    skip_names = source.get("skip_names", set())
    exclude_dirs = source.get("exclude_dirs", set())
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if path.name in skip_names:
            continue
        if exclude_dirs and rel.parts and rel.parts[0] in exclude_dirs:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        yield str(rel), path


def title_of(text, key):
    import re
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else key


def main():
    parser = argparse.ArgumentParser(description="Sync doc trees to MDDB")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--missing-only", action="store_true")
    parser.add_argument("--sync-deletes", action="store_true")
    parser.add_argument("--source", action="append",
                        help="limit to named source(s)")
    args = parser.parse_args()

    sources = SOURCES
    if args.source:
        wanted = set(args.source)
        sources = [s for s in SOURCES if s["name"] in wanted]
        missing = wanted - {s["name"] for s in sources}
        if missing:
            print(f"unknown source(s): {', '.join(sorted(missing))}")
            return 2

    stats = {"added": 0, "updated": 0, "skipped": 0, "orphans": 0}
    for src in sources:
        root = src["dir"]
        coll = src["collection"]
        files = dict(iter_files(src))
        print(f"== {src['name']}: {root} -> {coll} ({len(files)} files)")
        if not root.is_dir():
            print("   warn: source dir missing — skipped")
            continue
        try:
            remote = list_docs(coll)
        except Exception as e:
            print(f"   warn: cannot list {coll}: {e} — skipped")
            continue

        seen = set()
        for key, path in files.items():
            seen.add(key)
            text = path.read_text(encoding="utf-8")
            md5 = hashlib.md5(text.encode()).hexdigest()
            meta = {
                "title": title_of(text, key),
                "source": "docs-sync",
                "repo": src["name"],
                "rel_path": key,
                "content_md5": md5,
                "last_synced": datetime.now().isoformat(),
            }
            existing = remote.get(key)
            if existing is None:
                print(f"   ADD {key}")
                if not args.dry_run:
                    add_doc(coll, key, text, meta)
                stats["added"] += 1
            elif meta_first(existing["meta"], "content_md5") == md5 \
                    or args.missing_only:
                stats["skipped"] += 1
            else:
                print(f"   UPD {key}")
                if not args.dry_run:
                    add_doc(coll, key, text, meta)
                stats["updated"] += 1

        for key in sorted(set(remote) - seen):
            stats["orphans"] += 1
            print(f"   ORPHAN {key} in {coll} (no file on disk)")
            if args.sync_deletes:
                if not args.dry_run:
                    delete_doc(coll, key, remote[key]["lang"])
                print(f"   DEL {key}")

    print("\nDone." + (" (dry-run)" if args.dry_run else ""))
    print(f"  added={stats['added']} updated={stats['updated']} "
          f"unchanged={stats['skipped']} orphans={stats['orphans']}")
    if stats["orphans"] and not args.sync_deletes:
        print("  re-run with --sync-deletes to remove orphans")
    return 0


if __name__ == "__main__":
    sys.exit(main())
