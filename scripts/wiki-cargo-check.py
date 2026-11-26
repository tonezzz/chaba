#!/usr/bin/env python3
"""Read-only check for the Education: Cargo table on wiki.h3.

Answers one question for OPS-0038: does the Cargo table exist and does it
contain the expected Education lesson? Read-only API calls only — wiki writes
still go through board-api /wiki/page or /publish.

  python3 scripts/wiki-cargo-check.py                       # live wiki
  python3 scripts/wiki-cargo-check.py --fixture f.json     # offline/replay
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_API = "https://wiki.h3.gizmo-thailand.com/api.php"
DEFAULT_TABLE = "Education"
DEFAULT_TOPIC = "ada-ocb-skills"


def fetch(api: str, params: dict) -> dict:
    url = api + "?" + urllib.parse.urlencode({**params, "format": "json"})
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _table_names(raw) -> list[str]:
    out = []
    for entry in raw or []:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict):
            for key in ("name", "table", "_table", "title"):
                if entry.get(key):
                    out.append(str(entry[key]))
                    break
    return out


def _rows(raw) -> list[dict]:
    out = []
    for entry in raw or []:
        if isinstance(entry, dict):
            out.append(entry.get("title") if isinstance(entry.get("title"), dict)
                       else entry)
    return out


def check(tables: dict, query: dict, table: str = DEFAULT_TABLE,
          topic: str = DEFAULT_TOPIC) -> dict:
    """Evaluate API payloads (live or fixture) into a deterministic verdict."""
    names = _table_names(tables.get("cargotables"))
    present = any(n.lower() == table.lower() for n in names)
    rows = _rows(query.get("cargoquery"))
    found = bool(topic) and any(
        str(r.get("topic") or r.get("_pageName") or "").lower() == topic.lower()
        for r in rows)
    reasons = []
    if not present:
        reasons.append(f"table {table!r} missing from action=cargotables "
                       f"(found: {names})")
    if not found:
        reasons.append(f"topic {topic!r} not found in cargoquery rows")
    return {
        "ok": present and found,
        "table": table,
        "topic": topic,
        "table_present": present,
        "tables_seen": names,
        "topic_found": found,
        "rows": len(rows),
        "reasons": reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--table", default=DEFAULT_TABLE)
    ap.add_argument("--topic", default=DEFAULT_TOPIC)
    ap.add_argument("--fixture", type=Path,
                    help="JSON {cargotables, cargoquery} instead of live API")
    args = ap.parse_args()

    if args.fixture:
        payload = json.loads(args.fixture.read_text(encoding="utf-8"))
        tables, query = payload.get("cargotables", {}), payload.get("cargoquery", {})
    else:
        tables = fetch(args.api, {"action": "cargotables"})
        query = fetch(args.api, {"action": "cargoquery",
                                 "tables": args.table,
                                 # cargoquery API rejects bare underscore field
                                 # names as aliases — alias _pageName explicitly.
                                 "fields": "_pageName=page,topic,next_review",
                                 "limit": 500})
    result = check(tables, query, args.table, args.topic)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
