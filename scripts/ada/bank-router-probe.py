#!/usr/bin/env python3
"""bank-router-probe.py — Phase-0 measurement for card nest-bank-router.

Measures the wall-time split of ada_memory_search bank='all' fan-out by
replaying the exact request shape against the production mddb, WITHOUT
touching ada-pi: per-bank POST /v1/vector-search, run the same way
memory_ops.memory_search does (asyncio.gather over every bank).

Two arms split embed vs index time:

  text   — {"query": "..."} — mddb embeds the query remotely
           (gemini-ollama-proxy -> Gemini) then searches. This is what
           production does today, N embeds per fan-out.
  vector — {"queryVector": [...]} — pre-embedded random unit vector,
           no remote embed: pure index scan + doc load + network.

  full - embed = the remote embedding share of each call. If it
  dominates, a bank router only partly helps — the bigger win is
  embedding the query ONCE (or skipping memory entirely), which the
  Phase-0 doc must weigh separately.

Usage:
  python3 scripts/ada/bank-router-probe.py --iters 8
  MDDB_BASE_URL=http://100.102.134.91:11023 python3 ... --json out.json
"""
import argparse
import asyncio
import json
import math
import os
import random
import statistics
import time
import urllib.request

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.102.134.91:11023")
MDDB = MDDB.removesuffix("/v1").removesuffix("/")

# Banks assigned to instance 'tony' — mirrors the live registry
# (~/.config/ada/memory-banks.json on idc03, read 2026-10-08). Speaker
# tony sees all but the person-scoped banks of others (personal-kk,
# personal-testo) — the ACL trims those from bank='all'.
BANKS_TONY = {
    "chaba-archive": "chaba-archive",
    "chaba-docs": "chaba-docs",
    "cms": "ada-cms-pages",
    "developer": "ada-ha-bank-developer-tony",
    "devin": "ada-ha-bank-devin-tony",
    "devin-handoff": "ada-ha-bank-devin-handoff",
    "devin-kb": "devin-kb",
    "documents": "documents",
    "general": "ada-ha-bank-general",
    "github": "ada-ha-bank-github",
    "home": "ada-ha-bank-home",
    "ideas": "ada-ha-bank-ideas-tony",
    "infrastructure-ssot": "infrastructure-ssot",
    "kb-development": "kb-development",
    "kb-features": "kb-features",
    "kb-operations": "kb-operations",
    "kb-system": "kb-system",
    "note": "ada-ha-bank-note-tony",
    "ops-scenarios": "ada-ha-scenario-reports",
    "people": "ada-ha-bank-people",
    "personal": "ada-ha-bank-personal-tony",
    "purchase": "ada-ha-bank-purchase",
    "tony-projects": "ada-ha-bank-projects-tony",
}

# Realistic memory-recall queries, mined-style (mixed EN/TH like prod).
QUERIES = [
    "what is the wifi password",
    "when is KK's birthday",
    "did we already buy washing machine parts",
    "เครื่องซักผ้าซ่อมแล้วยัง",
    "what did Tony ask about the UPS battery",
    "which camera keeps going offline at night",
    "what was the migration plan for idc01",
    "dad's flight arrival time",
]


def _post(path: str, payload: dict, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(
        MDDB + path, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _unit_vector(dims: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    v = [rng.gauss(0, 1) for _ in range(dims)]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def timed_search(collection: str, arm: str, query: str,
                 qvec: list[float] | None) -> tuple[float, int, float | None]:
    """One /v1/vector-search. Returns (wall_s, hits, server_ms)."""
    payload: dict = {"collection": collection, "topK": 5,
                     "includeContent": False}
    if arm == "text":
        payload["query"] = query
    else:
        payload["queryVector"] = qvec
    t0 = time.monotonic()
    try:
        resp = _post("/v1/vector-search", payload)
    except Exception as exc:  # surface as a marked row, not a crash
        return time.monotonic() - t0, -1, None
    wall = time.monotonic() - t0
    stats = resp.get("searchStats") or {}
    return wall, len(resp.get("results") or []), stats.get("durationMs")


async def one_fanout(arm: str, query: str, qvec: list[float] | None,
                     banks: dict[str, str]) -> dict:
    """Replicates memory_search bank='all': parallel per-bank searches."""
    loop = asyncio.get_running_loop()

    async def call(name: str, coll: str):
        return name, await loop.run_in_executor(
            None, timed_search, coll, arm, query, qvec)

    t0 = time.monotonic()
    pairs = await asyncio.gather(*(call(n, c) for n, c in banks.items()))
    total = time.monotonic() - t0
    per_bank = {n: {"wall_s": round(w, 4), "hits": h, "server_ms": ms}
                for n, (w, h, ms) in pairs}
    return {"arm": arm, "query": query, "total_s": round(total, 4),
            "banks": per_bank}


def pct(vals: list[float], p: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    k = (len(s) - 1) * p / 100
    f = math.floor(k)
    return s[f] + (s[min(f + 1, len(s) - 1)] - s[f]) * (k - f)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=8)
    ap.add_argument("--dims", type=int, default=768)
    ap.add_argument("--json", help="write raw rows to this path")
    ap.add_argument("--banks", default="",
                    help="comma-separated bank names (default: all tony)")
    args = ap.parse_args()

    banks = BANKS_TONY
    if args.banks:
        keep = set(args.banks.split(","))
        banks = {k: v for k, v in BANKS_TONY.items() if k in keep}

    qvec = _unit_vector(args.dims, seed=7)
    rows: list[dict] = []

    # Warm-up: one text + one vector call so index/proxy connections are hot.
    _post("/v1/vector-search", {"collection": "ada-ha-bank-general",
                                "query": "warmup", "topK": 1,
                                "includeContent": False})
    _post("/v1/vector-search", {"collection": "ada-ha-bank-general",
                                "queryVector": qvec, "topK": 1,
                                "includeContent": False})

    for i in range(args.iters):
        q = QUERIES[i % len(QUERIES)]
        for arm in ("text", "vector"):
            row = await one_fanout(arm, q, qvec, banks)
            row["iter"] = i
            rows.append(row)
            slowest = max(row["banks"].items(), key=lambda kv: kv[1]["wall_s"])
            print(f"iter {i} {arm:6s} total={row['total_s']*1000:7.0f}ms "
                  f"slowest={slowest[0]} {slowest[1]['wall_s']*1000:.0f}ms")

    # --- summary -------------------------------------------------------
    def totals(arm: str) -> list[float]:
        return [r["total_s"] for r in rows if r["arm"] == arm]

    per_bank_text: dict[str, list[float]] = {}
    per_bank_vec: dict[str, list[float]] = {}
    for r in rows:
        tgt = per_bank_text if r["arm"] == "text" else per_bank_vec
        for n, b in r["banks"].items():
            tgt.setdefault(n, []).append(b["wall_s"])

    t, v = totals("text"), totals("vector")
    print("\n=== fan-out totals (bank='all', %d banks) ===" % len(banks))
    for name, vals in (("text(embed+search)", t), ("vector(search-only)", v)):
        print(f"{name:22s} p50={pct(vals,50)*1000:7.0f}ms "
              f"p95={pct(vals,95)*1000:7.0f}ms n={len(vals)}")
    print("\n=== per-bank wall p50: text vs vector (embed share = delta) ===")
    for n in sorted(per_bank_text):
        tt, vv = per_bank_text[n], per_bank_vec.get(n, [])
        print(f"{n:20s} text_p50={pct(tt,50)*1000:6.0f}ms "
              f"vec_p50={pct(vv,50)*1000:6.0f}ms "
              f"embed~{(pct(tt,50)-pct(vv,50))*1000:6.0f}ms")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"mddb": MDDB, "iters": args.iters,
                       "banks": banks, "rows": rows}, f, indent=1)
        print(f"\nraw rows -> {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
