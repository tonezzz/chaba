#!/usr/bin/env python3
"""embed-pool-warm-ping — keep bge-m3 hot on the embed-pool upstreams.

Cold-model trap (spike gotcha, docs/ssot/jobs/mddb/2026-11-18-cms-plane-bge-m3-migration-runbook.yml):
an ollama upstream whose bge-m3 keep_alive expired takes ~21s to cold-load —
longer than the shim's 8s timeout — so it racks up consecutive fails, gets a
60s dead_until, and can flap there indefinitely while siblings saturate.
Warming omen manually during the spike moved drain 2->14 docs/min instantly.

This pings each PRIMARY upstream's /api/embed with a one-token input often
enough to stay under the model's keep_alive window. Deferred-tier upstreams
(nest-bridge device workers, EMBED_POOL_DEFER_UPSTREAMS) are deliberately NOT
pinged — they are opportunistic and must not be woken on a timer.

Env:
  EMBED_POOL_WARM_UPSTREAMS  comma list of ollama base URLs to warm
                             (default: the two bge-m3 primaries behind
                             embed-pool-shim on idc03)
  EMBED_POOL_WARM_MODEL      model name (default bge-m3:latest — must match
                             what the shim requests, i.e. MDDB_EMBEDDING_MODEL)
  EMBED_POOL_WARM_TIMEOUT_S  per-upstream timeout (default 60 — cold bge-m3
                             load measured ~21-90s on a busy host; a timed-out
                             ping still triggers the load server-side)

Usage: python3 embed-pool-warm-ping.py   # systemd oneshot every ~4min
"""
import json
import os
import sys
import urllib.request

UPSTREAMS = [u.strip().rstrip("/") for u in os.environ.get(
    "EMBED_POOL_WARM_UPSTREAMS",
    "http://100.102.134.91:11434,http://100.75.102.88:11434",
).split(",") if u.strip()]
MODEL = os.environ.get("EMBED_POOL_WARM_MODEL", "bge-m3:latest")
TIMEOUT = float(os.environ.get("EMBED_POOL_WARM_TIMEOUT_S", "60"))


def ping(base: str) -> tuple[bool, str]:
    body = json.dumps({
        "model": MODEL,
        "input": "warmup",
        "keep_alive": "30m",
    }).encode()
    req = urllib.request.Request(
        base + "/api/embed", data=body,
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            r = json.loads(resp.read())
        n = len((r.get("embeddings") or [[]])[0])
        return True, f"{n}d"
    except Exception as exc:
        return False, str(exc)[:200]


def main() -> int:
    if not UPSTREAMS:
        print("no upstreams configured", file=sys.stderr)
        return 1
    # Concurrent — a cold upstream can take ~60s+ to load; sequential pings
    # could overrun the 4min cadence on a fully-cold pool.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(UPSTREAMS)) as ex:
        results = list(ex.map(lambda u: (u,) + ping(u), UPSTREAMS))
    ok = 0
    for u, good, detail in results:
        ok += good
        print(f"{'ok ' if good else 'FAIL'} {u} {MODEL} {detail}")
    # All-fail is the only hard error — a single cold/dead upstream is
    # exactly what the pool's dead_until cooldown is for.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
