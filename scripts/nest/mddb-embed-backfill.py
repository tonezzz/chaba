#!/usr/bin/env python3
"""mddb-embed-backfill — copy a collection from the leader mddb into the
local-embedding instance (mddb-embed :11028, ollama bge-m3) so the bank
has a self-owned vector space (MEM-0788).

Resume-safe: skips keys already present on the target. Runs on any host
that can reach both endpoints — designed for idc03 (same-host hops).

Usage: mddb-embed-backfill.py [--collection ada-ha-bank-devin-tony]
                              [--force]

--force re-adds every source doc instead of skipping existing keys —
repairs docs stored without vectors (write-embed timeout drops) by
pushing them back through the target's embed queue.
"""
import ast
import json
import sys
import time
import urllib.request
import urllib.error

SRC = "http://100.102.134.91:11023/v1"
DST = "http://100.102.134.91:11028/v1"
COLLECTION = "ada-ha-bank-devin-tony"


def post(base, path, payload, timeout=60):
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def docs(base, include_content):
    out = post(base, "/search", {"collection": COLLECTION, "limit": 10000,
                                 "include_content": include_content})
    return out if isinstance(out, list) else (
        out.get("results") or out.get("documents") or [])


def main():
    coll = COLLECTION
    if "--collection" in sys.argv:
        coll = sys.argv[sys.argv.index("--collection") + 1]

    force = "--force" in sys.argv
    have = {d.get("key") for d in docs(DST, False)}
    src = docs(SRC, True)
    todo = [d for d in src if (force or d.get("key") not in have)
            and d.get("contentMd")]
    print(f"source {len(src)} docs | already on target {len(have)} | "
          f"to copy {len(todo)}", flush=True)

    ok = fail = 0
    t0 = time.time()
    for i, d in enumerate(todo):
        meta = d.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = ast.literal_eval(meta)
            except Exception:
                meta = {}
        try:
            post(DST, "/add", {"collection": coll, "key": d["key"],
                               "lang": d.get("lang") or "en",
                               "contentMd": d["contentMd"],
                               "meta": meta})
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  FAIL {d.get('key')}: {e}", flush=True)
        if (i + 1) % 25 == 0:
            rate = (i + 1) / max(time.time() - t0, 1)
            eta = (len(todo) - i - 1) / max(rate, 0.01)
            print(f"  {i+1}/{len(todo)} — {rate:.1f}/s — eta {eta/60:.0f}m",
                  flush=True)

    print(f"done: {ok} copied, {fail} failed in "
          f"{(time.time()-t0)/60:.0f}m", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
