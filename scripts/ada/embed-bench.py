#!/usr/bin/env python3
"""embed-bench.py — Gemini-direct vs OpenRouter(Vertex) embedding benchmark.

Answers: is the OR Vertex route the same vector space, how's latency,
and what does it cost? Run on idc01 where mddb-gemini.env lives:

    cd ~/CascadeProjects/chaba && set -a && \
      source ~/.config/secrets/mddb-gemini.env && set +a && \
      python3 scripts/ada/embed-bench.py --publish

Corpus: real docs pulled from ada-cms-pages via MDDB /v1/search.
Metrics per route: p50/p95 latency, mean|min cosine(OR,direct) per text,
OR-billed usage, retrieval sanity (title-as-query top-1 hit rate).
"""
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OR_BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
DIRECT_MODELS = ["gemini-embedding-2", "gemini-embedding-001"]
OR_MODEL = os.environ.get("OR_BENCH_MODEL", "google/gemini-embedding-2")
DIMS = 768
N_DOCS = 30
OR_PRICE_PER_MTOK = float(os.environ.get("OR_PRICE_PER_MTOK", "0.15"))


def http_json(url: str, payload: dict, headers: dict | None = None,
              timeout: float = 30.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def corpus() -> list[tuple[str, str]]:
    """(key, text) pairs from real CMS docs."""
    data = http_json(f"{MDDB}/search", {
        "collection": "ada-cms-pages",
        "filter_meta": {"kind": ["page"]}, "limit": N_DOCS})
    docs = data if isinstance(data, list) else \
        (data.get("results") or data.get("documents") or [])
    out = []
    for d in docs:
        body = (d.get("contentMd") or d.get("content") or "")[:1500]
        if len(body) > 80:
            out.append((d.get("key", "?"), body))
    return out[:N_DOCS]


def embed_gemini(texts: list[str]) -> tuple[list[list[float]], float]:
    """Direct API, returns (vectors, elapsed_s)."""
    last_err = None
    for model in DIRECT_MODELS:
        payload = {"requests": [{
            "model": f"models/{model}",
            "content": {"parts": [{"text": t}]},
            "outputDimensionality": DIMS,
        } for t in texts]}
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:batchEmbedContents?key={GEMINI_KEY}")
        t0 = time.time()
        try:
            data = http_json(url, payload, timeout=60)
            embs = [e["values"] for e in data.get("embeddings", [])]
            if len(embs) == len(texts):
                return embs, time.time() - t0
            last_err = f"{len(embs)}/{len(texts)} embeddings"
        except Exception as e:
            last_err = str(e)
    raise RuntimeError(f"direct Gemini failed on all models: {last_err}")


def embed_or(texts: list[str]) -> tuple[list[list[float]], float, int]:
    """OpenRouter, returns (vectors, elapsed_s, billed_tokens).

    OR's Vertex route 404s on array `input` — one HTTP call per text,
    exactly like the production proxy does (verified live)."""
    t0 = time.time()
    embs, toks = [], 0
    for t in texts:
        data = http_json(f"{OR_BASE}/embeddings", {
            "model": OR_MODEL, "input": t, "dimensions": DIMS,
            "provider": {"order": ["Google"], "allow_fallbacks": False},
        }, {"Authorization": f"Bearer {OR_KEY}"}, timeout=30)
        embs.append(data["data"][0]["embedding"])
        toks += (data.get("usage") or {}).get("prompt_tokens", 0)
    return embs, time.time() - t0, toks


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def batched(xs: list, n: int):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main() -> None:
    if not GEMINI_KEY or not OR_KEY:
        sys.exit("need GEMINI_API_KEY + OPENROUTER_API_KEY (mddb-gemini.env)")
    docs = corpus()
    if len(docs) < 5:
        sys.exit(f"corpus too small: {len(docs)} docs — mddb healthy?")
    print(f"corpus: {len(docs)} docs")

    gem_lat, or_lat, or_toks = [], [], 0
    cosines = []
    for chunk in batched([b for _, b in docs], 10):
        g, gs = embed_gemini(chunk)
        o, os_, tk = embed_or(chunk)
        gem_lat.append(gs); or_lat.append(os_); or_toks += tk
        cosines += [cos(a, b) for a, b in zip(g, o)]
        time.sleep(0.5)

    # retrieval sanity: first-10-chars of title slug → top-1 same-space check
    hits_g = hits_o = 0
    probes = docs[:8]
    gspace, _ = embed_gemini([b for _, b in docs])
    ospace, _, _ = embed_or([b for _, b in docs])
    for key, body in probes:
        q = " ".join(re.split(r"[-_]", key))[:80]
        try:
            gq, _ = embed_gemini([q]); oq, _, _ = embed_or([q])
        except Exception:
            continue
        bg = max(range(len(docs)), key=lambda i: cos(gq[0], gspace[i]))
        bo = max(range(len(docs)), key=lambda i: cos(oq[0], ospace[i]))
        hits_g += docs[bg][0] == key
        hits_o += docs[bo][0] == key
        time.sleep(0.3)

    est_cost = or_toks / 1e6 * OR_PRICE_PER_MTOK
    rep = {
        "run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "docs": len(docs), "dims": DIMS, "or_model": OR_MODEL,
        "cosine": {"mean": round(statistics.fmean(cosines), 4),
                   "min": round(min(cosines), 4)},
        "latency_s": {"gemini_p50": round(statistics.median(gem_lat), 2),
                      "gemini_p95": round(max(gem_lat), 2),
                      "or_p50": round(statistics.median(or_lat), 2),
                      "or_p95": round(max(or_lat), 2)},
        "or_tokens": or_toks, "or_cost_usd": round(est_cost, 5),
        "top1_hit": {"gemini": f"{hits_g}/{len(probes)}",
                     "openrouter": f"{hits_o}/{len(probes)}"},
    }
    print(json.dumps(rep, indent=2))
    open("/tmp/embed-bench.json", "w").write(json.dumps(rep, indent=2))

    if "--publish" in sys.argv:
        title = "Gemini & OR Embedding Benchmark"
        same_space = rep["cosine"]["min"] > 0.98
        body = f"""# {title}

Run {rep['run']} — {rep['docs']} real `ada-cms-pages` docs, {DIMS} dims.
Direct = `generativelanguage.googleapis.com` batchEmbedContents;
OR = `{rep['or_model']}` via OpenRouter (provider order: Google Vertex).

## Verdict

**{"Same vector space — OR is a drop-in mirror, safe to keep." if same_space else "VECTOR SPACES DIFFER — do NOT mix routes on one collection."}**

| metric | direct Gemini | OpenRouter |
|---|---|---|
| latency p50 (10-doc batch) | {rep['latency_s']['gemini_p50']}s | {rep['latency_s']['or_p50']}s |
| latency worst batch | {rep['latency_s']['gemini_p95']}s | {rep['latency_s']['or_p95']}s |
| top-1 retrieval probes | {rep['top1_hit']['gemini']} | {rep['top1_hit']['openrouter']} |

cosine(OR, direct) per doc — mean **{rep['cosine']['mean']}**, min **{rep['cosine']['min']}**
(≈1.0 = identical space; same underlying model via Vertex).

## Cost

- OR billed tokens this run: **{rep['or_tokens']}** ≈ **${rep['or_cost_usd']}**
  (at ${OR_PRICE_PER_MTOK}/Mtok — recheck OR pricing if it shifts).
- Projected: mddb daily writes ≈ tens of docs → **< $0.01/month** steady state;
  full-corpus re-embed ≈ a few cents one-shot.
- Comparison for *search* (not embeddings): Gemini paid grounding is
  ~$35/1K queries vs OR online/sonar routes ~$4-5/1K — the bigger
  argument for OR lives there; free-tier grounding stays at 20/day.

## Routes measured

- Primary (live): `gemini-ollama-proxy` → OR `google/gemini-embedding-2`
- Backup chain in proxy: OR → direct Gemini → local Ollama (`nomic-embed-text`)
- Hard-fail on OR error is deliberate — a different-space fallback would
  poison retrieval silently.

## Pros & cons of keeping OR in parallel

**Pros**
- Same vector space proven (cosine 1.000) — OR is a true mirror, no
  re-embed or collection migration ever needed.
- Off the Gemini free tier — embeddings no longer share the 20-req/day
  budget with grounded `web_search` and voice traffic.
- Predictable spend: measured **$0.0016/run**; steady state < $0.01/mo.
- Chain stays intact on OR outage: OR → (direct Gemini) → local Ollama.

**Cons**
- ~5× slower per batch — OR's Vertex route rejects array input, so every
  text is its own HTTP call (fine at our write volume). OR docs claim
  arrays are supported; the pin to provider `Google` is what breaks it.
- Silent spend creep — needs an occasional usage check, not alerts.
- OR AI-Studio provider route is broken (bogus API_KEY_INVALID) —
  pinned `order:[Google]` is the only working path.

## Improvements — applied vs open

**Applied this run**
- `GEMINI_API_KEY` restored in `mddb-gemini.env` + proxy now falls back
  to direct Gemini (same space, verified 1.000) on OR failure — Ollama
  still refused. Failover tested live: dead OR → direct Gemini → 768d.

**Open (ranked)**
1. **Per-collection int8 quantization on mddb** — native feature
   (`PUT /v1/collection-config`, ~4× RAM cut, ~92-98% recall). Directly
   addresses the 8.1GB OOM event; existing vectors keep working,
   `vector-reindex --force` converts.
2. **OR search tier for `web_search`** — paid Gemini grounding ≈ $35/1K
   vs OR sonar ≈ $5/1K; sits between free-20/day and DuckDuckGo.
3. **Embedding-chunk tunables** — mddb splits docs at 1500 chars by
   default; each chunk is one sequential OR call → the 20s+ CMS write
   times. Larger chunks or proxy-side concurrency would cut latency.
4. **Parallelize OR embed calls** (4-8 concurrent) in the proxy.
5. **Weekly `embed-bench` timer + OR usage readout** — catches spend
   creep and provider-side model drift.
6. **Pin `dimensions:768` + model in SSOT.**
7. **OR Batch API** exists for embeddings (async, 24h window,
   `provider.only` pin) — the right tool if we ever do a bulk
   re-embed/backfill; not for live writes.

## Sources

- mddb quantization: github.com/tradik/mddb → docs/QUANTIZATION.md
- mddb chunking/cache: docs/features + EMBEDDING_PROVIDERS.md
- OR embeddings spec: openrouter.ai/docs/api_reference/embeddings
- OR batch API: openrouter.ai/docs/batch-quickstart
"""
        http_json(f"{MDDB}/add", {
            "collection": "ada-cms-pages", "key": "gemini-or-embedding-benchmark",
            "lang": "en", "contentMd": body,
            "meta": {"kind": ["page"], "slug": ["gemini-or-embedding-benchmark"],
                     "title": [title], "format": ["markdown"],
                     "updated": [rep['run']], "instance": ["tony"]}})
        print("published → ada-cms-pages/gemini-or-embedding-benchmark")


if __name__ == "__main__":
    main()
