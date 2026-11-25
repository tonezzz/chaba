#!/usr/bin/env python3
"""Warm-ping the embed-pool bge-m3 upstreams so ollama keeps the model
resident (card mddb-cms-11027-embed-coverage-gap-250-do-e35321, action 3).

Why: embed-pool-shim :11436 races fleet ollama upstreams; ollama unloads
bge-m3 after ~5min idle, and the first embed on a cold upstream pays the
full model-load latency — during degraded windows the shim 504s
("no upstream answered in time") and mddb drops embed jobs, silently
removing docs from vector search (queue dropped=910->1762 observed).

How: read the live upstream list from the shim's GET /health (primaries
+ deferred — auto-tracks fleet changes), then POST a tiny /api/embed to
EACH upstream directly (not through the shim race, which would only warm
the winner). Run on a timer shorter than ollama's keep_alive.

Env:
  EMBED_POOL_SHIM_URL   default http://127.0.0.1:11436 (run on idc03)
  EMBED_WARM_MODEL      default bge-m3
  EMBED_WARM_INPUT      default "warmup"
  EMBED_WARM_TIMEOUT_S  per-upstream timeout, default 60 (cold load is slow)
  EMBED_WARM_UPSTREAMS  comma list — overrides shim /health discovery

Exit 0 when at least one upstream answered; 1 when all failed (a host
being asleep is normal — only a total miss is worth a failed unit).
"""
import json
import os
import sys
import time
import urllib.request

SHIM = os.environ.get("EMBED_POOL_SHIM_URL", "http://127.0.0.1:11436")
MODEL = os.environ.get("EMBED_WARM_MODEL", "bge-m3")
WARM_INPUT = os.environ.get("EMBED_WARM_INPUT", "warmup")
TIMEOUT = int(os.environ.get("EMBED_WARM_TIMEOUT_S", "60"))


def _req(url, payload=None, timeout=TIMEOUT):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"content-type": "application/json"} if data else {})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def upstreams():
    override = os.environ.get("EMBED_WARM_UPSTREAMS", "")
    if override.strip():
        return [u.strip().rstrip("/") for u in override.split(",") if u.strip()]
    health = _req(f"{SHIM}/health", timeout=15)
    ups = list(health.get("upstreams") or [])
    ups += list(health.get("defer_upstreams") or [])
    return [u.rstrip("/") for u in ups]


def warm(base):
    t0 = time.time()
    r = _req(f"{base}/api/embed",
             {"model": MODEL, "input": WARM_INPUT}, timeout=TIMEOUT)
    embs = r.get("embeddings") or []
    if not embs:
        raise RuntimeError("empty embeddings in response")
    return time.time() - t0


def main():
    try:
        ups = upstreams()
    except Exception as exc:
        print(f"shim /health unreachable at {SHIM}: {exc} — cannot "
              f"discover upstreams; set EMBED_WARM_UPSTREAMS", file=sys.stderr)
        return 1
    if not ups:
        print("no upstreams configured on shim", file=sys.stderr)
        return 1
    ok = 0
    for u in ups:
        try:
            ms = warm(u) * 1000
            print(f"  ok   {u}  {ms:.0f}ms")
            ok += 1
        except Exception as exc:
            print(f"  FAIL {u}  {exc}", file=sys.stderr)
    print(f"embed-pool-warm: {ok}/{len(ups)} upstreams warm")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
