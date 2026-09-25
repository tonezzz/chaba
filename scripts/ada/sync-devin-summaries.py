#!/usr/bin/env python3
"""Sync Devin session summaries into the ada-ha-bank-devin-tony MDDB
bank so Ada can recall "what did we work on" via ada_memory_search /
ada_session_recall(bank="devin").

Sources:
- ~/.local/share/devin/cli/summaries/history_*.md — CLI thread dumps,
  keyed devin/<hex-thread-id>.
- ~/.local/share/devin/summaries/*.md — devin-desktop per-session
  summaries, keyed devin-session/<friendly-name>. These carry the
  desktop session identity the hex keys lack.

- Skips empty files (continuation stubs).
- Idempotent: compares remote contentMd; unchanged files are skipped.
- Meta: kind=note, source=import, written_by=devin-cli/devin-desktop,
  session_id/session_name from the filename, date from file mtime — the
  standard provenance fields let the vault sync leave these docs alone
  (remote-only, kept).

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

CLI_SUMMARIES = Path.home() / ".local/share/devin/cli/summaries"
NAMED_SUMMARIES = Path.home() / ".local/share/devin/summaries"
COLLECTION = "ada-ha-bank-devin-tony"
# MDDB drops the connection on very large docs. Oversized files keep the
# distilled head (structured summary) plus the tail, where the outcome of
# the session usually lands.
MAX_CHARS = 50_000
HEAD_FRACTION = 0.6


def clip(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    head = int(MAX_CHARS * HEAD_FRACTION)
    tail = MAX_CHARS - head - 128  # room for the truncation marker
    omitted = len(text) - head - tail
    marker = f"\n\n[... {omitted} chars truncated ...]\n\n"
    return text[:head] + marker + text[-tail:]


def iter_docs(src_dir: Path):
    """Yield (file, key, meta_overrides) for every source doc."""
    for f in sorted(src_dir.glob("history_*.md")):
        sid = f.stem.removeprefix("history_")
        yield f, f"devin/{sid}", {"session_id": [sid], "attribute": [sid],
                                  "subject": ["devin-session"],
                                  "written_by": ["devin-cli"]}
    for f in sorted(NAMED_SUMMARIES.glob("*.md")):
        name = f.stem
        yield f, f"devin-session/{name}", {"session_name": [name],
                                           "attribute": [name],
                                           "subject": ["devin-session-summary"],
                                           "written_by": ["devin-desktop"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=CLI_SUMMARIES)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mddb = ada_sync.Mddb(args.mddb, timeout=120)  # large histories embed slowly
    remote = {d.get("key"): d for d in mddb.list_docs(COLLECTION)}

    added = skipped = empty = unchanged = total = 0
    for f, key, extra_meta in iter_docs(args.dir):
        total += 1
        text = f.read_text(errors="replace").strip()
        if not text:
            empty += 1
            continue
        body = clip(text)
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
            "date": [mtime],
            **extra_meta,
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
          f"{skipped} failed (of {total} files)")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
