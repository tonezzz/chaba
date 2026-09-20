#!/usr/bin/env python3
"""Back up Ada memory-bank MDDB collections to JSON files.

Banks are the only memory state with no copy outside MDDB — voice-written
docs exist nowhere else until exported to the vault inbox. This dumps every
bank collection (plus the rolling recall summaries) so a lost/corrupted
MDDB can be rebuilt.

Privacy: personal banks are written to a local-only dir
(default ~/.local/share/ada-backups/), never into the repo.

Usage:
  backup-mddb-banks.py                # dump all banks (shared→repo, personal→local)
  backup-mddb-banks.py --dry-run      # report what would be written
  backup-mddb-banks.py --git          # write + git add/commit+push the repo dump
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

DEFAULT_OUT = REPO / "backups/ada-memory"
DEFAULT_PRIVATE_OUT = Path.home() / ".local/share/ada-backups/ada-memory"


def dump_collection(mddb: "ada_sync.Mddb", collection: str) -> dict:
    docs = mddb.list_docs(collection)
    return {
        "collection": collection,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "doc_count": len(docs),
        "docs": docs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT,
                    help="repo-side dump dir (git-backable)")
    ap.add_argument("--private-output", type=Path, default=DEFAULT_PRIVATE_OUT,
                    help="local-only dir for personal banks")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--git", action="store_true",
                    help="git add+commit+push the repo dump dir afterwards")
    args = ap.parse_args()

    mapping = ada_sync.load_bank_map()
    mddb = ada_sync.Mddb(args.mddb)

    # Bank collections + the rolling recall summaries (the other recallable
    # state that exists only in MDDB).
    import yaml
    banks = yaml.safe_load(ada_sync.SSOT.read_text()).get("banks") or {}
    instances = {i for spec in banks.values() for i in (spec.get("instances") or [])}

    collections: list[tuple[str, str]] = []  # (collection, privacy)
    for m in mapping:
        privacy = "private" if m["dir"].startswith("personal") else "repo"
        collections.append((m["collection"], privacy))
    for inst in sorted(instances):
        collections.append((f"ada-ha-recall-summary-{inst}", "repo"))

    written = 0
    for collection, privacy in dict.fromkeys(collections):
        try:
            data = dump_collection(mddb, collection)
        except Exception as exc:
            print(f"  ! {collection}: {exc}")
            continue
        if data["doc_count"] == 0:
            print(f"  = {collection} (empty, skipped)")
            continue
        outdir = args.private_output if privacy == "private" else args.output
        path = outdir / f"{collection}.json"
        print(f"  {'(dry) ' if args.dry_run else ''}w {collection} -> {path} "
              f"({data['doc_count']} docs{' [local-only]' if privacy == 'private' else ''})")
        if not args.dry_run:
            outdir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        written += 1

    print(f"\n{written} collection(s) dumped")

    if args.git and not args.dry_run and args.output.exists():
        subprocess.run(["git", "-C", str(REPO), "add", str(args.output)], check=True)
        msg = f"backup(ada-memory): MDDB bank dump {datetime.now(timezone.utc):%Y-%m-%d}"
        subprocess.run(["git", "-C", str(REPO), "commit", "-qm", msg])
        subprocess.run(["git", "-C", str(REPO), "push", "origin", "HEAD"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
