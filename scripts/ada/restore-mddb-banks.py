#!/usr/bin/env python3
"""Restore Ada memory banks from backup dumps back into MDDB.

Reads dumps written by backup-mddb-banks.py (backups/ada-memory/*.json, or
~/.local/share/ada-backups/ada-memory/ for personal banks) and upserts every
doc via /v1/add — safe to re-run; same-key docs are overwritten with the
backup version.

Usage:
  restore-mddb-banks.py                              # restore everything found
  restore-mddb-banks.py --collection ada-ha-bank-note-tony
  restore-mddb-banks.py --file backups/ada-memory/ada-ha-bank-note-tony.json \
      --collection ada-ha-bank-note-tony-restore-test   # drill: verify a dump
  restore-mddb-banks.py --dry-run
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

DEFAULT_DIRS = [REPO / "backups/ada-memory",
                Path.home() / ".local/share/ada-backups/ada-memory"]


def restore_file(mddb: "ada_sync.Mddb", path: Path, collection: str | None,
                 dry: bool) -> int:
    data = json.loads(path.read_text())
    target = collection or data.get("collection") or path.stem
    docs = data.get("docs") or []
    n = 0
    for doc in docs:
        key = doc.get("key")
        if not key:
            print(f"  ! {path.name}: doc without key — skipped")
            continue
        print(f"  {'(dry) ' if dry else ''}w {target}:{key}")
        if not dry:
            mddb.add(target, key, doc.get("contentMd") or doc.get("content_md") or "",
                     doc.get("meta") or {})
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--collection",
                    help="restore only this collection — or override the dump's "
                         "collection name (drill/verify into a scratch collection)")
    ap.add_argument("--file", type=Path, help="restore a single dump file")
    ap.add_argument("--dir", action="append", type=Path, default=[],
                    help="extra dump dirs to scan (repo + private dirs are default)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mddb = ada_sync.Mddb(args.mddb)

    if args.file:
        files = [args.file]
    else:
        files = []
        for d in (args.dir or DEFAULT_DIRS):
            if d.is_dir():
                files += sorted(d.glob("*.json"))
        if args.collection:
            files = [f for f in files if f.stem == args.collection]
            args.collection = None  # restoring to its own name, not remapping
    if not files:
        print("no dump files found")
        return 1

    total = 0
    for f in files:
        print(f"{f.name}:")
        total += restore_file(mddb, f, args.collection, args.dry_run)
    print(f"\n{total} doc(s) {'would be ' if args.dry_run else ''}restored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
