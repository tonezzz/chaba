#!/usr/bin/env python3
"""Sync Devin CLI session summaries into the ada-ha-bank-devin-tony MDDB
bank so Ada can recall "what did we work on" via ada_memory_search /
ada_session_recall(bank="devin").

Source: ~/.local/share/devin/cli/summaries/history_*.md
- Skips empty files (continuation stubs).
- Idempotent: compares remote contentMd; unchanged files are skipped.
- Meta: kind=note, source=import, written_by=devin-cli, session_id from
  the filename, date from file mtime — the standard provenance fields let
  the vault sync leave these docs alone (remote-only, kept).

Usage:
  sync-devin-summaries.py            # sync all summaries
  sync-devin-summaries.py --dry-run
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

SUMMARIES = Path.home() / ".local/share/devin/cli/summaries"
COLLECTION = "ada-ha-bank-devin-tony"
# MDDB drops the connection on very large docs; the structured summary
# lives at the top of these files anyway — keep the distilled head.
MAX_CHARS = 50_000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=SUMMARIES)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mddb = ada_sync.Mddb(args.mddb, timeout=120)  # large histories embed slowly
    remote = {d.get("key"): d for d in mddb.list_docs(COLLECTION)}
    files = sorted(args.dir.glob("history_*.md"))

    added = skipped = empty = unchanged = 0
    for f in files:
        text = f.read_text(errors="replace").strip()
        if not text:
            empty += 1
            continue
        sid = f.stem.removeprefix("history_")
        key = f"devin/{sid}"
        body = text[:MAX_CHARS]
        mtime = datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()
        old = remote.get(key)
        if old and (old.get("contentMd") or "") == body:
            unchanged += 1
            continue
        meta = {
            "kind": ["note"],
            "status": ["active"],
            "scope": ["tony"],
            "bank": ["devin"],
            "source": ["import"],
            "written_by": ["devin-cli"],
            "session_id": [sid],
            "date": [mtime],
            "subject": ["devin-session"],
            "attribute": [sid],
        }
        print(f"  {'(dry) ' if args.dry_run else ''}{'~' if old else '+'} {key} "
              f"({len(body)} chars, {mtime})")
        if not args.dry_run:
            try:
                mddb.add(COLLECTION, key, body, meta)
            except Exception as exc:
                print(f"  ! {key} failed ({exc}) — continuing")
                skipped += 1
                continue
        added += 1

    print(f"\n{added} synced, {unchanged} unchanged, {empty} empty skipped, "
          f"{skipped} failed (of {len(files)} files)")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
