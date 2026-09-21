#!/usr/bin/env python3
"""Seed the `purchase` memory bank's criteria docs into MDDB.

Reads banks.purchase.seed from the memory-banks SSOT and upserts each doc
into the bank's MDDB collection (default ada-ha-bank-purchase). Idempotent:
existing keys are skipped unless --force.

The seeds are the starter rulebook for POST /api/decision/check — edit them
in the SSOT, re-run this script; Ada can also extend them at runtime via
ada_remember.

Usage:
  seed-purchase-criteria.py                      # seed against default MDDB
  seed-purchase-criteria.py --force              # overwrite existing docs
  MDDB_BASE_URL=http://127.0.0.1:11023/v1 seed-purchase-criteria.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

import yaml

SSOT = Path(__file__).resolve().parents[2] / "docs/ssot/apps/ssot.apps.ada-memory-banks.yml"
MDDB_BASE_URL = os.environ.get("MDDB_BASE_URL", "http://100.68.142.13:11023/v1").rstrip("/")


def _post(path: str, payload: dict, timeout: int = 20) -> dict | None | str:
    """POST/PATCH to MDDB. Returns 'missing' on a 400 not-found so callers
    can distinguish 'no such doc' from a real failure."""
    req = urllib.request.Request(
        f"{MDDB_BASE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST" if path != "/update" else "PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        if exc.code == 400 and "not found" in body.lower():
            return "missing"
        print(f"  {path} failed: HTTP {exc.code} {body}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"  {path} failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="overwrite docs that already exist")
    ap.add_argument("--bank", default="purchase", help="bank name in the SSOT (default: purchase)")
    args = ap.parse_args()

    data = yaml.safe_load(SSOT.read_text())
    bank = (data.get("banks") or {}).get(args.bank) or {}
    seeds = bank.get("seed") or []
    collection = str(bank.get("mddb_collection") or "")
    if not seeds or not collection:
        raise SystemExit(f"{SSOT}: banks.{args.bank} has no seed list or collection")

    today = date.today().isoformat()
    ok = failed = skipped = 0
    for item in seeds:
        key = str(item.get("key") or "")
        text = str(item.get("text") or "").strip()
        if not key or not text:
            print(f"  skip malformed seed: {item!r}")
            failed += 1
            continue
        if not args.force:
            existing = _post("/get", {"collection": collection, "key": key, "lang": "en"})
            if existing == "missing":
                pass
            elif existing:
                skipped += 1
                print(f"  exists  {key}")
                continue
            else:
                failed += 1
                continue
        meta = {
            "bank": [args.bank],
            "kind": [str(item.get("kind") or "preference")],
            "scope": ["shared" if bank.get("scope") == "shared" else "tony"],
            "status": ["active"],
            "valid_from": [today],
            "last_verified": [today],
            "source": ["import"],
            "written_by": ["seed-purchase-criteria"],
        }
        if item.get("subject"):
            meta["subject"] = [str(item["subject"])]
        # /add embeds inline — embedding via the Ollama proxy takes ~15s/doc.
        result = _post("/add", {
            "collection": collection, "key": key, "lang": "en",
            "contentMd": text, "meta": meta,
        }, timeout=120)
        if result is None:
            failed += 1
        else:
            ok += 1
            print(f"  seeded  {key}")

    print(f"done: {ok} seeded, {skipped} existing, {failed} failed -> {collection}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
