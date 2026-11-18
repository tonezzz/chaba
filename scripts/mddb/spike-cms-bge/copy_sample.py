#!/usr/bin/env python3
"""Spike: copy a CMS-plane sample from mddb-cms :11027 into the scratch
bge-m3 instance on idc02 :11029 (card spike-migrate-mddb-cms-plane-11027-embed).

Read-only against prod :11027 — pages /v1/search (include_content) and
re-POSTs each doc to the scratch instance's /v1/add so it embeds through
the instance's own queue (same path a real migration would take).

Usage:
    python3 copy_sample.py [--cms-pages-limit N] [--queue-hi 3000]
"""
import argparse
import ast
import json
import sys
import time
import urllib.request

SRC = "http://100.102.134.91:11027"          # prod CMS plane (read-only)
DST = "http://100.123.163.11:11029"          # scratch bge-m3 on idc02
PAGE = 1000

# (collection, doc cap) — cap None = all docs with contentMd
SAMPLE = [
    ("chaba-lessons", None),
    ("kb-development", None),
    ("kb-features", None),
    ("kb-operations", None),
    ("kb-system", None),
    ("ada-cms-pages", 400),
]


def _post(url, payload, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def docs(base, coll):
    out, offset, seen = [], 0, set()
    while True:
        d = _post(f"{base}/v1/search",
                  {"collection": coll, "limit": PAGE, "offset": offset,
                   "include_content": True})
        page = d if isinstance(d, list) else (
            d.get("results") or d.get("documents") or [])
        fresh = [x for x in page if x.get("key") not in seen]
        if page and not fresh:
            break
        seen.update(x.get("key") for x in page)
        out.extend(page)
        offset += len(page)
        if len(page) < PAGE:
            break
    return out


def queue_stats():
    try:
        d = _post(f"{DST}/v1/vector-stats", {}, timeout=30)
        q = d.get("queue") or {}
        return int(q.get("depth") or 0), int(q.get("dropped") or 0)
    except Exception:
        return -1, -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cms-pages-limit", type=int, default=400)
    ap.add_argument("--queue-hi", type=int, default=3000)
    args = ap.parse_args()

    total = fail = 0
    t0 = time.time()
    for coll, cap in SAMPLE:
        if coll == "ada-cms-pages":
            cap = args.cms_pages_limit
        try:
            src_docs = [d for d in docs(SRC, coll) if d.get("contentMd")]
        except Exception as e:
            print(f"{coll}: fetch failed {e}", file=sys.stderr)
            continue
        todo = src_docs[:cap] if cap else src_docs
        print(f"{coll}: src={len(src_docs)} todo={len(todo)}", flush=True)
        copied = 0
        for i, d in enumerate(todo):
            depth, dropped = queue_stats()
            while depth >= args.queue_hi:
                print(f"  queue depth {depth} (dropped {dropped}) — waiting",
                      flush=True)
                time.sleep(20)
                depth, dropped = queue_stats()
            meta = d.get("meta") or {}
            if isinstance(meta, str):
                try:
                    meta = ast.literal_eval(meta)
                except Exception:
                    meta = {}
            try:
                _post(f"{DST}/v1/add",
                      {"collection": coll, "key": d["key"],
                       "lang": d.get("lang") or "en",
                       "contentMd": d["contentMd"], "meta": meta},
                      timeout=60)
                copied += 1
            except Exception as e:
                fail += 1
                print(f"  FAIL {d.get('key')}: {e}", file=sys.stderr)
            if (i + 1) % 100 == 0:
                el = time.time() - t0
                print(f"  {coll}: {i+1}/{len(todo)} "
                      f"({copied/el*60:.0f} docs/min add-rate)", flush=True)
            time.sleep(0.02)
        total += copied
        print(f"{coll}: copied={copied}", flush=True)
    el = time.time() - t0
    depth, dropped = queue_stats()
    print(f"DONE: {total} docs delivered in {el:.0f}s "
          f"({total/el*60:.0f} docs/min), failed={fail}; "
          f"queue depth={depth} dropped={dropped} (embeds drain async)")


if __name__ == "__main__":
    main()
