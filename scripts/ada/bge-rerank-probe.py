#!/usr/bin/env python3
"""bge-rerank-probe.py — latency probe for the warm rerank endpoint
(MEM-1129 serving-architecture decision, card
bge-production-serving-architecture-rera-e6ba35).

Answers the question the 2026-11-08 eval could not: what does /rerank
actually cost per top-K depth on the LIVE service (shared Omen GPU,
serialized _lock, tailscale RTT)? The eval harness measured ~57ms/pair
fp32 -> "top-10 ~565ms"; the Nov 18-19 shadow soak logged rerank_ms
1078-1412 for 9-10 docs (~110-140ms/pair effective). Run this on an
idle GPU window (and again under load) before picking the serving arm.

  GET  /health                      -> ok/model/device/served (open)
  POST /rerank {query, docs[]}      -> {scores[]}  (bearer token)

Usage:
  RERANK_URL=http://100.75.102.88:11555 \
  RERANK_AUTH_TOKEN=<token> \
  python3 bge-rerank-probe.py --depths 3,5,10,20 --iters 5

Token env fallback order: RERANK_AUTH_TOKEN, ADA_BGE_SHADOW_RERANK_TOKEN.
Docs are synthetic ~600-char memory-like texts (deterministic) — latency
depends on pair count x tokenized length, not content.
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.request

BASE = os.environ.get("RERANK_URL", "http://100.75.102.88:11555").rstrip("/")
TOKEN = (os.environ.get("RERANK_AUTH_TOKEN")
         or os.environ.get("ADA_BGE_SHADOW_RERANK_TOKEN") or "")

_FILLS = [
    "the wifi password is written on the router label in the study",
    "Tony prefers window seats on overnight flights to Bangkok",
    "the car battery was replaced on 2026-10-02, warranty until 2028",
    "lesson: always verify by surface not by service before closing",
    "the garden irrigation timer runs at 06:30 and 18:30 daily",
    "MDDB leader plane is :11023, CMS plane :11027, ops :11025",
]


def _doc(i: int) -> str:
    # ~600 chars of deterministic memory-like text per doc id.
    body = " ".join(_FILLS[(i + j) % len(_FILLS)] for j in range(4))
    return f"doc-{i}: {body} " * 3


def _post(path: str, payload: dict, timeout: float) -> dict:
    headers = {"content-type": "application/json"}
    if TOKEN:
        headers["authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(), headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _get(path: str, timeout: float = 10) -> dict:
    return json.loads(urllib.request.urlopen(BASE + path, timeout=timeout).read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depths", default="3,5,10,20",
                    help="comma-separated rerank depths (doc counts)")
    ap.add_argument("--iters", type=int, default=5,
                    help="timed iterations per depth (first is cold, "
                         "reported separately)")
    ap.add_argument("--warmup", type=int, default=1,
                    help="untimed warmup calls before measuring")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--query", default="what is the wifi password")
    a = ap.parse_args()

    try:
        health = _get("/health")
    except Exception as exc:
        print(f"health check failed: {exc}", file=sys.stderr)
        return 1
    print(f"health: {json.dumps(health)}")
    if not health.get("ok"):
        return 1
    if not TOKEN:
        print("warning: no RERANK_AUTH_TOKEN/ADA_BGE_SHADOW_RERANK_TOKEN "
              "— /rerank will 401", file=sys.stderr)

    depths = [int(d) for d in a.depths.split(",") if d.strip()]
    max_depth = max(depths)
    docs = [{"id": str(i), "text": _doc(i)} for i in range(max_depth)]

    # Warmup — first call pays any lazy init; excluded from stats.
    for _ in range(a.warmup):
        try:
            _post("/rerank", {"query": a.query, "docs": docs[:max_depth]},
                  a.timeout)
        except Exception as exc:
            print(f"warmup failed: {exc}", file=sys.stderr)
            return 1

    print(f"{'depth':>5} {'n':>3} {'p50_ms':>8} {'p95_ms':>8} "
          f"{'min_ms':>8} {'max_ms':>8} {'ms/pair':>8}")
    for depth in depths:
        lat = []
        for _ in range(a.iters):
            t0 = time.monotonic()
            try:
                res = _post("/rerank",
                            {"query": a.query, "docs": docs[:depth]},
                            a.timeout)
            except Exception as exc:
                print(f"depth={depth} failed: {exc}", file=sys.stderr)
                return 1
            lat.append((time.monotonic() - t0) * 1000.0)
            if len(res.get("scores") or []) != depth:
                print(f"depth={depth}: got "
                      f"{len(res.get('scores') or [])} scores", file=sys.stderr)
                return 1
        lat.sort()
        p50 = statistics.median(lat)
        p95 = lat[min(len(lat) - 1, int(0.95 * len(lat) + 0.9999) - 1)]
        print(f"{depth:>5} {a.iters:>3} {p50:>8.0f} {p95:>8.0f} "
              f"{lat[0]:>8.0f} {lat[-1]:>8.0f} {p50 / depth:>8.1f}")
    print(f"\nserved counter now: {_get('/health').get('served')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
