#!/usr/bin/env python3
"""Dump doc listings (key|lang|title|snippet) for golden-set authoring.

Read-only against prod :11027. Usage:
    python3 dump_corpus.py --out corpus_dump.txt [--per-collection N]
"""
import argparse
import json
import urllib.request

SRC = "http://100.102.134.91:11027"
PAGE = 1000

COLLS = [
    "chaba-lessons", "chaba-docs", "devin-kb", "documents",
    "kb-development", "kb-features", "kb-operations", "kb-system",
    "chaba-architecture", "chaba-archive", "chaba-glossary", "ssot",
    "ada-cms-pages", "infrastructure-ssot",
]


def post(url, payload, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def docs(coll):
    out, offset, seen = [], 0, set()
    while True:
        d = post(f"{SRC}/v1/search",
                 {"collection": coll, "limit": PAGE, "offset": offset,
                  "include_content": True})
        page = d if isinstance(d, list) else (
            d.get("results") or d.get("documents") or [])
        fresh = [x for x in page if (x.get("key"), x.get("lang")) not in seen]
        if page and not fresh:
            break
        seen.update((x.get("key"), x.get("lang")) for x in page)
        out.extend(page)
        offset += len(page)
        if len(page) < PAGE:
            break
    return out


def meta_title(meta):
    if isinstance(meta, str):
        try:
            meta = json.loads(meta.replace("'", '"'))
        except Exception:
            return ""
    m = meta or {}
    for k in ("title", "wiki_title", "topic", "slug"):
        v = m.get(k)
        if v:
            return str(v[0] if isinstance(v, list) else v)
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="corpus_dump.txt")
    ap.add_argument("--per-collection", type=int, default=0,
                    help="0 = all docs; N = systematic sample of N")
    args = ap.parse_args()

    with open(args.out, "w") as f:
        for coll in COLLS:
            try:
                ds = docs(coll)
            except Exception as e:
                f.write(f"\n##### {coll} FETCH-FAIL {e}\n")
                continue
            if args.per_collection and len(ds) > args.per_collection:
                step = len(ds) / args.per_collection
                ds = [ds[int(i * step)] for i in range(args.per_collection)]
            f.write(f"\n##### {coll} ({len(ds)} shown)\n")
            for d in ds:
                body = (d.get("contentMd") or "").replace("\n", " ")[:220]
                f.write(f"{coll}|{d.get('key')}|{d.get('lang')}|"
                        f"{meta_title(d.get('meta'))}|{body}\n")
            print(f"{coll}: {len(ds)}", flush=True)


if __name__ == "__main__":
    main()
