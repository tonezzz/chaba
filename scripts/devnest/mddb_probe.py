#!/usr/bin/env python3
"""mddb_probe.py — read-only MDDB surface probe for lane-scoped agents
(card nest-opencode-executor-eval, MEM-0871 eval template).

This is the ONLY network tool the mddb-sequence profile's bash allowlist
permits. Every subcommand is a bounded GET (or a read-only /v1/search
page scan); there are no mutating endpoints here by construction — an
agent cannot reach delete/truncate/add/export through this probe no
matter what arguments it passes. The held-out verifier recomputes the
same facts independently.

Banks (tailnet, idc03):
    main  :11023  leader — memory plane (ada-ha-*, ssot, kb, reports)
    ops   :11026  no-embed telemetry (host-logs, host-logs-state)
    cms   :11027  chaba content plane (ada-cms-*, chaba-*, kb-*)
    embed :11028  local-embedding bank (mirrors leader collections)

Subcommands:
    banks                                   list the bank map
    health <bank>                           GET /health
    vector-stats <bank>                     GET /v1/vector-stats
    config <bank> <collection>              GET /v1/collection-config?collection=
    expired <bank> <collection> <ts_key> <days> [--pages N]
        bounded scan: up to N pages of /v1/search (read-only POST),
        counts docs whose meta[ts_key][0] is older than now-<days>.
        Prints {collection, ts_key, days, cutoff, scanned, expired,
        complete} — complete=false means the page cap was hit and the
        count is a lower bound.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BANKS = {
    "main": "http://idc03:11023",
    "ops": "http://idc03:11026",
    "cms": "http://idc03:11027",
    "embed": "http://idc03:11028",
}

PAGE = 5000          # matches prune-old-docs.py — stays ~1s even deep
MAX_PAGES = 40       # hard ceiling: 40*5000 = 200k docs scanned max
REQ_TIMEOUT = 60


def _get(url: str, timeout: int = 30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post(base: str, path: str, body: dict, timeout: int = REQ_TIMEOUT):
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _bank(name: str) -> str:
    if name not in BANKS:
        raise SystemExit(f"unknown bank {name!r} — have: "
                         f"{sorted(BANKS)}")
    return BANKS[name]


def cmd_expired(bank: str, collection: str, ts_key: str, days: int,
                pages: int) -> dict:
    base = _bank(bank)
    pages = max(1, min(int(pages), MAX_PAGES))
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=days)).isoformat()
    scanned = expired = 0
    complete = True
    offset = 0
    for _ in range(pages):
        try:
            page = _post(base, "/v1/search",
                         {"collection": collection, "query": "",
                          "limit": PAGE, "offset": offset})
        except urllib.error.HTTPError as e:
            return {"collection": collection, "error": f"http {e.code}",
                    "scanned": scanned, "expired": expired,
                    "complete": False}
        except Exception as e:
            return {"collection": collection, "error": str(e),
                    "scanned": scanned, "expired": expired,
                    "complete": False}
        if not page:
            break
        scanned += len(page)
        for d in page:
            ts = ((d.get("meta") or {}).get(ts_key) or [""])[0]
            if ts and ts < cutoff:
                expired += 1
        offset += len(page)
        if len(page) < PAGE:
            break
    else:
        complete = False
    if scanned == pages * PAGE:
        complete = False          # hit the cap exactly — may be more
    return {"collection": collection, "ts_key": ts_key, "days": days,
            "cutoff": cutoff, "scanned": scanned, "expired": expired,
            "complete": complete}


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "banks":
        print(json.dumps(BANKS, indent=1))
        return 0
    if cmd == "health" and len(argv) == 3:
        print(json.dumps(_get(f"{_bank(argv[2])}/health"), indent=1))
        return 0
    if cmd == "vector-stats" and len(argv) == 3:
        print(json.dumps(_get(f"{_bank(argv[2])}/v1/vector-stats",
                              timeout=90), indent=1))
        return 0
    if cmd == "config" and len(argv) == 4:
        print(json.dumps(_get(
            f"{_bank(argv[2])}/v1/collection-config"
            f"?collection={urllib.parse.quote(argv[3])}"), indent=1))
        return 0
    if cmd == "expired" and len(argv) >= 6:
        pages = MAX_PAGES
        if "--pages" in argv:
            i = argv.index("--pages")
            if i + 1 < len(argv):
                pages = int(argv[i + 1])
        t0 = time.monotonic()
        out = cmd_expired(argv[2], argv[3], argv[4],
                          int(argv[5]), pages)
        out["wall_s"] = round(time.monotonic() - t0, 1)
        print(json.dumps(out, indent=1))
        return 0 if "error" not in out else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
