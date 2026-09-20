#!/usr/bin/env python3
"""Consolidate voice-inbox notes into curated memory-bank directories.

The sync script exports voice-written MDDB docs to vault `inbox/<bank>/`
for human review. Once reviewed, this job promotes each note into the
matching bank directory — provenance stays in the frontmatter
(source=voice / written_by=ada_remember become origin_* on the next
sync push, which then stamps the doc written_by=obsidian-vault).

Usage:
  consolidate-memory.py             # move all inbox notes into their banks
  consolidate-memory.py --dry-run   # print the plan, move nothing
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Reuse the sync script's vault/bank-map/frontmatter helpers.
_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)


def consolidate(vault: Path, dry: bool) -> int:
    inbox = vault / "inbox"
    if not inbox.is_dir():
        print("no inbox/ — nothing to consolidate")
        return 0

    # bank name -> list of (dir, scope) targets from the registry mapping.
    targets: dict[str, list[dict]] = {}
    for m in ada_sync.load_bank_map():
        targets.setdefault(m["bank"], []).append(m)

    moved = skipped = 0
    for bank_dir in sorted(p for p in inbox.iterdir() if p.is_dir()):
        bank = bank_dir.name
        options = targets.get(bank)
        if not options:
            print(f"! {bank}: not a registered bank — skipping")
            skipped += 1
            continue
        for note_path in sorted(bank_dir.glob("*.md")):
            note = ada_sync.parse_note(note_path)
            scope = ""
            if note:
                scope = str(note["frontmatter"].get("scope") or "")
            # Multi-dir banks (personal) pick the dir matching the note's
            # scope (personal/tony, personal/michael); single-dir banks are flat.
            target = None
            if len(options) == 1:
                target = options[0]["dir"]
            elif scope:
                for o in options:
                    if o["dir"].endswith(f"/{scope}"):
                        target = o["dir"]
                        break
            if target is None:
                print(f"! {note_path.relative_to(vault)}: cannot resolve target dir "
                      f"(bank {bank!r}, scope {scope!r}) — skipping")
                skipped += 1
                continue
            dest = vault / target / note_path.name
            rel_src, rel_dst = note_path.relative_to(vault), dest.relative_to(vault)
            if dest.exists():
                print(f"! {rel_src}: {rel_dst} already exists — skipping")
                skipped += 1
                continue
            print(f"{'> ' if not dry else '  (dry) '}{rel_src} -> {rel_dst}")
            if not dry:
                dest.parent.mkdir(parents=True, exist_ok=True)
                note_path.rename(dest)
            moved += 1
    print(f"\n{moved} moved, {skipped} skipped" + (" (dry run)" if dry else ""))
    return moved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", type=Path, default=REPO / "docs/ada-memory")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    consolidate(args.vault, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
