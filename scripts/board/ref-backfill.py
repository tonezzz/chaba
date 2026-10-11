#!/usr/bin/env python3
"""ref-backfill.py — assign CAT-NNNN refs to cards that lack one.

Idempotent: cards with a valid ref are untouched. Order is stable —
sorted by (updated, filename) so re-runs never renumber. Category comes
from the card's tags via board-api's REF_CATS (single source of truth).

Run on the served checkout (chaba-tony-dell) so refs land under the
single-writer flow:

  python3 scripts/board/ref-backfill.py            # apply
  python3 scripts/board/ref-backfill.py --dry-run  # preview
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import yaml

BAPI = Path(__file__).resolve().with_name("board-api.py")
spec = importlib.util.spec_from_file_location("board_api", BAPI)
bapi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bapi)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cards = sorted(
        bapi.CARD_DIR.glob("*.yml"),
        key=lambda p: (
            str((yaml.safe_load(p.read_text()) or {}).get("updated") or ""),
            p.name,
        ),
    )
    # dry-run peeks at the counter without burning numbers
    seq_n = (int(bapi.REF_SEQ.read_text().strip() or 0)
             if bapi.REF_SEQ.exists() else bapi._ref_seed())
    changed = 0
    for p in cards:
        c = yaml.safe_load(p.read_text()) or {}
        ref = str(c.get("ref") or "")
        if bapi.REF_RE.match(ref):
            continue
        if args.dry_run:
            seq_n += 1
            new = f"{bapi.ref_cat(c, {})}-{seq_n:04d}"
        else:
            new = bapi.alloc_ref(bapi.ref_cat(c, {}))
        c["ref"] = new
        c.setdefault("comms", []).append(
            {"at": bapi.now(), "from": "chaba",
             "text": f"ref assigned: {new}"})
        if args.dry_run:
            print(f"DRY {new} -> {c.get('id') or p.stem}")
        else:
            p.write_text(yaml.safe_dump(c, allow_unicode=True,
                                        sort_keys=False, width=110))
            print(f"{new} -> {c.get('id') or p.stem}")
        changed += 1
    print(f"{'would assign' if args.dry_run else 'assigned'} {changed} ref(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
