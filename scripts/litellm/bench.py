#!/usr/bin/env python3
"""bench.py — latency + cost per call class through the LiteLLM gateway,
compared against direct provider calls.

Runs on idc03 (needs ~/.config/secrets/{litellm-keys,mddb-gemini,gemini-keys}.env):

    python3 scripts/litellm/bench.py            # json to stdout
    python3 scripts/litellm/bench.py --publish  # + ada-cms-pages/llm-gateway-bench

Gateway legs hit http://100.102.134.91:4000/v1 (chat classes) and /v1/embeddings
(embedding class). Direct legs hit generativelanguage.googleapis.com and
openrouter.ai for the same prompt — the delta is the gateway's tax on latency.
Cost is the delta of the bench virtual key's spend before/after the run, so it
reflects LiteLLM's own accounting, not an estimate.
"""
import json
import os
import statistics
import sys
import time
import urllib.request

GW = os.environ.get("LITELLM_URL", "http://100.102.134.91:4000").rstrip("/")
GW_KEY = os.environ.get("LITELLM_KEY") or os.environ.get("LITELLM_KEY_BENCH", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY_PAID", "")
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OR_BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
MDDB = os.environ.get("MDDB_BASE_URL", "http://100.102.134.91:11027/v1")

CHAT_CLASSES = ["tool-call", "summary", "voice-aux", "classify", "bench"]
N_CALLS = int(os.environ.get("BENCH_N", "5"))
PROMPT = "Reply with exactly one word: the capital of France."


def http_json(url, payload=None, headers=None, timeout=30.0):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def gw_chat(model):
    t0 = time.time()
    d = http_json(f"{GW}/v1/chat/completions",
                  {"model": model, "messages": [{"role": "user", "content": PROMPT}],
                   "max_tokens": 8},
                  {"Authorization": f"Bearer {GW_KEY}"}, timeout=60)
    dt = time.time() - t0
    u = d.get("usage") or {}
    return dt, u.get("total_tokens", 0), (d.get("model") or "")


def gw_embed(texts):
    t0 = time.time()
    d = http_json(f"{GW}/v1/embeddings",
                  {"model": "embedding", "input": texts},
                  {"Authorization": f"Bearer {GW_KEY}"}, timeout=60)
    return time.time() - t0, (d.get("usage") or {}).get("total_tokens", 0)


def direct_gemini(model="gemini-2.5-flash-lite"):
    t0 = time.time()
    d = http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}",
        {"contents": [{"parts": [{"text": PROMPT}]}],
         "generationConfig": {"maxOutputTokens": 8}}, timeout=60)
    dt = time.time() - t0
    return dt, (d.get("usageMetadata") or {}).get("totalTokenCount", 0)


def direct_or(model="google/gemini-2.5-flash-lite"):
    t0 = time.time()
    d = http_json(f"{OR_BASE}/chat/completions",
                  {"model": model, "messages": [{"role": "user", "content": PROMPT}],
                   "max_tokens": 8},
                  {"Authorization": f"Bearer {OR_KEY}"}, timeout=60)
    return time.time() - t0, (d.get("usage") or {}).get("total_tokens", 0)


def key_spend():
    try:
        d = http_json(f"{GW}/key/info?key={GW_KEY}",
                      headers={"Authorization": f"Bearer {GW_KEY}"})
        return float((d.get("info") or {}).get("spend", 0) or 0)
    except Exception:
        return None


def summarize(ts):
    return {"n": len(ts), "p50_s": round(statistics.median(ts), 3),
            "p95_s": round(max(ts), 3), "mean_s": round(statistics.fmean(ts), 3)}


def main():
    if not GW_KEY:
        sys.exit("need LITELLM_KEY/LITELLM_KEY_BENCH (litellm-keys.env)")
    spend0 = key_spend()
    rep = {"run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "gateway": GW, "classes": {}, "direct": {}, "embedding": {}}

    for cls in CHAT_CLASSES:
        ts, toks, upstreams = [], 0, set()
        for _ in range(N_CALLS):
            try:
                dt, tk, up = gw_chat(cls)
                ts.append(dt); toks += tk; upstreams.add(up)
            except Exception as e:
                rep["classes"].setdefault(cls, {})["error"] = str(e)[:160]
        if ts:
            rep["classes"][cls] = {**summarize(ts), "tokens": toks,
                                   "upstream": sorted(upstreams)}
        time.sleep(0.2)

    try:
        ts, tk = gw_embed(["gateway bench probe " + str(i) for i in range(3)])
        rep["embedding"]["gateway"] = {"batch_s": round(ts, 3), "tokens": tk}
    except Exception as e:
        rep["embedding"]["gateway"] = {"error": str(e)[:160]}

    if GEMINI_KEY:
        ts = []
        for _ in range(3):
            try:
                dt, _ = direct_gemini(); ts.append(dt)
            except Exception as e:
                rep["direct"]["gemini-2.5-flash-lite"] = {"error": str(e)[:160]}
        if ts:
            rep["direct"]["gemini-2.5-flash-lite"] = summarize(ts)
    if OR_KEY:
        ts = []
        for _ in range(3):
            try:
                dt, _ = direct_or(); ts.append(dt)
            except Exception as e:
                rep["direct"]["or-gemini-2.5-flash-lite"] = {"error": str(e)[:160]}
        if ts:
            rep["direct"]["or-gemini-2.5-flash-lite"] = summarize(ts)

    spend1 = key_spend()
    if spend0 is not None and spend1 is not None:
        rep["gateway_spend_delta_usd"] = round(spend1 - spend0, 6)

    print(json.dumps(rep, indent=2))
    open("/tmp/llm-gateway-bench.json", "w").write(json.dumps(rep, indent=2))

    if "--publish" in sys.argv:
        rows = "\n".join(
            f"| {c} | {v.get('p50_s','–')} | {v.get('p95_s','–')} | "
            f"{v.get('tokens','–')} | {', '.join(v.get('upstream', [])) or v.get('error','–')} |"
            for c, v in rep["classes"].items())
        direct = "\n".join(
            f"| {k} | {v.get('p50_s','–')} | {v.get('p95_s','–')} |"
            for k, v in rep["direct"].items())
        body = f"""# LLM Gateway Bench

Run {rep['run']} — {N_CALLS} calls/class via `{GW}` (virtual key, bench budget).
Direct legs bypass the gateway for latency comparison; spend delta is the key's
LiteLLM-metered cost for the whole run.

## Per-class latency (gateway)

| class | p50 s | p95 s | tokens | upstream hit |
|---|---|---|---|---|
{rows}

## Direct provider latency (no gateway)

| route | p50 s | p95 s |
|---|---|---|
{direct}

## Embedding leg (3-text batch)

`{json.dumps(rep['embedding'])}`

## Gateway-metered spend for this run

**${rep.get('gateway_spend_delta_usd', 'n/a')}**
"""
        http_json(f"{MDDB}/add", {
            "collection": "ada-cms-pages", "key": "llm-gateway-bench",
            "lang": "en", "contentMd": body,
            "meta": {"kind": ["page"], "slug": ["llm-gateway-bench"],
                     "title": ["LLM Gateway Bench"], "format": ["markdown"],
                     "updated": [rep["run"]], "instance": ["idc03"]}})
        print("published → ada-cms-pages/llm-gateway-bench")


if __name__ == "__main__":
    main()
