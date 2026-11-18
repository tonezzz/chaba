#!/usr/bin/env python3
"""Recall + latency comparison for the bge-m3 CMS-plane spike.

Runs identical vector-search queries against:
  - prod gemini plane   :11027 (gemini-embedding-2, 768d)   — baseline
  - scratch bge plane   :11029 (bge-m3, 1024d, this spike)  — partial corpus
  - bge bank            :11028 (bge-m3, 1024d, full corpus) — same-space ref

Metrics per query: top-10 key overlap (intersection of returned doc keys),
mean reciprocal-rank-style agreement, and wall latency per instance.

Usage: python3 recall_compare.py [--json out.json]
"""
import argparse
import json
import time
import urllib.request

INSTANCES = {
    "gemini-11027": "http://100.102.134.91:11027",
    "bge-scratch-11029": "http://100.123.163.11:11029",
    "bge-bank-11028": "http://100.123.163.11:11028",
}

# (collection, query) — spread across the migrated surface
QUERIES = [
    ("chaba-lessons", "how does the kanban single-writer rule work"),
    ("chaba-lessons", "embedding provider outage recovery procedure"),
    ("chaba-lessons", "deploy a dashboard card change safely"),
    ("chaba-lessons", "home assistant automation naming conventions"),
    ("chaba-lessons", "git worktree dispatch session rules"),
    ("kb-operations", "restart a failed systemd user service on idc03"),
    ("kb-operations", "disk space cleanup procedure"),
    ("kb-operations", "tailscale connectivity troubleshooting"),
    ("kb-features", "board-api write endpoints"),
    ("kb-features", "mddb semantic search configuration"),
    ("kb-system", "quadlet container deployment"),
    ("kb-system", "ollama embedding model setup"),
    ("ada-cms-pages", "meeting notes summary"),
    ("ada-cms-pages", "project status report"),
    ("ada-cms-pages", "home automation dashboard"),
    ("ada-cms-pages", "thai language lesson"),
    ("documents", "network infrastructure"),
]


def vsearch(base, coll, query, k=10):
    body = json.dumps({"collection": coll, "query": query, "topK": k,
                       "limit": k, "includeContent": False}).encode()
    req = urllib.request.Request(
        f"{base}/v1/vector-search", data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        ms = (time.time() - t0) * 1000
        res = d.get("results") or []
        keys = [(x.get("document") or {}).get("key") or x.get("key")
                for x in res]
        return [k2 for k2 in keys if k2], ms, None
    except Exception as e:
        return [], (time.time() - t0) * 1000, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()

    rows = []
    lat = {k: [] for k in INSTANCES}
    for coll, q in QUERIES:
        got = {}
        for name, base in INSTANCES.items():
            keys, ms, err = vsearch(base, coll, q)
            got[name] = keys
            if err is None:
                lat[name].append(ms)
            if err:
                print(f"  {name} {coll} ERR {err}")
        base_set = got["gemini-11027"]
        row = {"collection": coll, "query": q,
               "n_gemini": len(base_set),
               "scratch_hits": len(got["bge-scratch-11029"]),
               "bank_hits": len(got["bge-bank-11028"]),
               "scratch_overlap": len(set(base_set)
                                      & set(got["bge-scratch-11029"])),
               "bank_overlap": len(set(base_set)
                                   & set(got["bge-bank-11028"]))}
        rows.append(row)
        print(f"{coll:16s} | gemini={row['n_gemini']:2d} "
              f"| scratch: {row['scratch_overlap']:2d}/{row['scratch_hits']:2d} overlap "
              f"| bank: {row['bank_overlap']:2d}/{row['bank_hits']:2d} overlap | {q[:45]}")

    print("\n--- latency (ms, mean/p90 over successful calls) ---")
    summary = {}
    for name, xs in lat.items():
        if not xs:
            continue
        xs.sort()
        p90 = xs[int(len(xs) * 0.9)] if len(xs) > 1 else xs[0]
        summary[name] = {"n": len(xs), "mean_ms": round(sum(xs) / len(xs)),
                         "p90_ms": round(p90)}
        print(f"  {name:22s} n={len(xs):2d} mean={summary[name]['mean_ms']:5d}ms "
              f"p90={summary[name]['p90_ms']:5d}ms")

    def agg(field, denom):
        pairs = [(r[field], r[denom]) for r in rows if r["n_gemini"]]
        return (sum(a for a, _ in pairs), sum(b for _, b in pairs))

    so, sb = agg("scratch_overlap", "n_gemini")
    bo, bb = agg("bank_overlap", "n_gemini")
    print(f"\ntop-10 overlap vs gemini-11027 baseline:")
    print(f"  bge-scratch-11029: {so}/{sb} = {so/sb*100:.1f}%"
          if sb else "  scratch: n/a")
    print(f"  bge-bank-11028:    {bo}/{bb} = {bo/bb*100:.1f}%"
          if bb else "  bank: n/a")
    out = {"queries": rows, "latency": summary,
           "scratch_overlap_pct": round(so / sb * 100, 1) if sb else None,
           "bank_overlap_pct": round(bo / bb * 100, 1) if bb else None}
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
