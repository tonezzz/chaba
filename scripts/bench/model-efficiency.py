#!/usr/bin/env python3
"""model-efficiency.py — fixed efficiency fixture across LLM providers.

Card: model-efficiency-refresh-deepseek-flint-providers (OPS-0878).
One deterministic case suite (qa / strict-json / tool-call / thai / gen /
vision) plus cold-vs-warm latency probes. Stdlib only so the same file can
run on tony-omen (local Ollama) and be piped to idc03 for gateway /
OpenRouter / Gemini / DeepSeek legs.

    python3 scripts/bench/model-efficiency.py --suite local  --json > out-local.json
    ssh idc03 'set -a; . ~/.config/secrets/litellm-keys.env; \
      . ~/.config/secrets/mddb-gemini.env; . ~/.config/secrets/gemini-keys.env; \
      set +a; python3 - --suite remote --json' \
      < scripts/bench/model-efficiency.py > out-remote.json

Secrets are read from env only; artifacts carry env-var NAMES, never values.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import statistics
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib

FIXTURE = "model-efficiency-v1"
WARM_REPEATS = 2

# ---------------------------------------------------------------- fixture --

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def vision_png_data_uri() -> str:
    """64x64 PNG: solid red left half, solid blue right half."""
    w = h = 64
    raw = bytearray()
    for _y in range(h):
        raw.append(0)  # filter: none
        for x in range(w):
            raw += bytes((220, 30, 30)) if x < 32 else bytes((30, 60, 220))
    png = (b"\x89PNG\r\n\x1a\n" +
           _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
           _png_chunk(b"IDAT", zlib.compress(bytes(raw))) +
           _png_chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


VISION_URI = vision_png_data_uri()
VISION_B64 = VISION_URI.split(",", 1)[1]

WEATHER_TOOL = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]

CASES = [
    {"name": "qa_japan", "system": None,
     "prompt": "Reply with exactly one word: the capital of Japan.",
     "max_tokens": 16, "check": "contains", "expect": ["tokyo"]},
    {"name": "json_extract", "system": "You output only valid JSON, no prose.",
     "prompt": ("Extract fields from this sentence and return JSON with keys "
                "name, role, city: 'Ada is an engineer based in Bangkok.'"),
     "max_tokens": 96, "check": "json_keys",
     "keys": ["name", "role", "city"]},
    {"name": "tool_weather", "system": "You are a helpful assistant with tools.",
     "prompt": "What is the weather in Bangkok right now?",
     "max_tokens": 128, "check": "tool_call", "tool_name": "get_weather",
     "arg_substr": "bangkok", "tools": WEATHER_TOOL},
    {"name": "thai_capital", "system": None,
     "prompt": "เมืองหลวงของญี่ปุ่นคืออะไร? ตอบสั้นๆ เป็นภาษาไทย",
     "max_tokens": 32, "check": "contains_any",
     "expect": ["โตเกียว", "tokyo", "Tokyo"]},
    {"name": "gen_bottle", "system": None,
     "prompt": ("Write a 120-word product description for a smart water "
                "bottle that tracks hydration."),
     "max_tokens": 220, "check": "min_chars", "n": 200},
    {"name": "vision_colors", "system": None,
     "prompt": ("This image has a solid red rectangle on the left half and a "
                "solid blue rectangle on the right half. Reply with JSON only: "
                "{\"left_color\":\"...\",\"right_color\":\"...\"}."),
     "max_tokens": 96, "check": "vision_colors", "vision": True},
]

# ------------------------------------------------------------------ http --

def http_json(url, payload=None, headers=None, timeout=60.0):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json", **(headers or {})})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            dt = time.time() - t0
            try:
                d = json.loads(body)
            except Exception:
                d = {"_raw": body[:400].decode("utf-8", "replace")}
            return {"ok": True, "status": r.status, "data": d, "s": dt}
    except urllib.error.HTTPError as e:
        body = e.read()[:1200]
        try:
            d = json.loads(body)
        except Exception:
            d = {"_raw": body.decode("utf-8", "replace")[:500]}
        return {"ok": False, "status": e.code, "data": d,
                "s": time.time() - t0, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "status": None, "data": None,
                "s": time.time() - t0, "error": str(e)[:300]}


# ------------------------------------------------------------- providers --

def _usage_openai(d):
    u = d.get("usage") or {}
    return {"prompt_tokens": u.get("prompt_tokens"),
            "completion_tokens": u.get("completion_tokens"),
            "total_tokens": u.get("total_tokens")}


def _norm_tool_calls(calls):
    out = []
    for c in calls or []:
        fn = c.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                pass
        out.append({"name": fn.get("name") or c.get("name"),
                    "arguments": args})
    return out


def call_openai(t, case):
    key = t.get("key") or "unused"
    headers = {"Authorization": f"Bearer {key}"}
    headers.update(t.get("extra_headers") or {})
    user_content = case["prompt"]
    if case.get("vision"):
        user_content = [
            {"type": "text", "text": case["prompt"]},
            {"type": "image_url",
             "image_url": {"url": VISION_URI}}]
    msgs = []
    if case.get("system"):
        msgs.append({"role": "system", "content": case["system"]})
    msgs.append({"role": "user", "content": user_content})
    payload = {"model": t["model"], "messages": msgs,
               "temperature": 0.2, "max_tokens": case["max_tokens"]}
    payload.update(t.get("extra_payload") or {})
    if case.get("tools"):
        payload["tools"] = case["tools"]
        payload["tool_choice"] = "auto"
    url = t["base"].rstrip("/") + "/chat/completions"
    r = http_json(url, payload, headers, t.get("timeout", 90))
    d = r.get("data") or {}
    msg = ((d.get("choices") or [{}])[0].get("message") or {})
    text = msg.get("content") or ""
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    return {"ok": r["ok"], "status": r.get("status"), "s": r["s"],
            "error": r.get("error"), "text": text,
            "tool_calls": _norm_tool_calls(msg.get("tool_calls")),
            "usage": _usage_openai(d),
            "resolved_model": d.get("model"),
            "error_detail": (d.get("error") or {}) if not r["ok"] else None}


def _gemini_tools_openai(tools):
    return [{"functionDeclarations": [
        {"name": f["function"]["name"],
         "description": f["function"].get("description", ""),
         "parameters": f["function"].get("parameters", {})}
        for f in tools]}]


def call_gemini(t, case):
    headers = {"x-goog-api-key": t.get("key") or "unused"}
    parts = [{"text": case["prompt"]}]
    if case.get("vision"):
        parts.append({"inline_data": {"mime_type": "image/png",
                                      "data": VISION_B64}})
    body = {"contents": [{"role": "user", "parts": parts}]}
    if case.get("system"):
        body["systemInstruction"] = {"parts": [{"text": case["system"]}]}
    gen = {"temperature": 0.2, "maxOutputTokens": case["max_tokens"]}
    if case["check"] == "json_keys":
        gen["responseMimeType"] = "application/json"
    body["generationConfig"] = gen
    if case.get("tools"):
        body["tools"] = _gemini_tools_openai(case["tools"])
        body["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
    url = (t["base"].rstrip("/") +
           f"/v1beta/models/{t['model']}:generateContent")
    r = http_json(url, body, headers, t.get("timeout", 90))
    d = r.get("data") or {}
    cand = (d.get("candidates") or [{}])[0]
    cparts = ((cand.get("content") or {}).get("parts") or [])
    text = "".join(p.get("text", "") for p in cparts if isinstance(p, dict))
    calls = []
    for p in cparts:
        fc = p.get("functionCall") if isinstance(p, dict) else None
        if fc:
            calls.append({"name": fc.get("name"),
                          "arguments": fc.get("args")})
    um = d.get("usageMetadata") or {}
    return {"ok": r["ok"], "status": r.get("status"), "s": r["s"],
            "error": r.get("error"), "text": text, "tool_calls": calls,
            "usage": {"prompt_tokens": um.get("promptTokenCount"),
                      "completion_tokens": um.get("candidatesTokenCount"),
                      "total_tokens": um.get("totalTokenCount")},
            "resolved_model": t["model"],
            "error_detail": (d.get("error") or {}) if not r["ok"] else None}


CALLERS = {"openai": call_openai, "openrouter": call_openai,
           "gemini": call_gemini}

# ---------------------------------------------------------------- checks --

def _extract_json(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def check_case(case, res):
    text = res.get("text") or ""
    low = text.lower()
    kind = case["check"]
    if kind == "contains":
        return all(e.lower() in low for e in case["expect"])
    if kind == "contains_any":
        return any(e.lower() in low for e in case["expect"])
    if kind == "min_chars":
        return len(text) >= case["n"]
    if kind == "json_keys":
        d = _extract_json(text)
        return isinstance(d, dict) and all(k in d for k in case["keys"])
    if kind == "tool_call":
        for c in res.get("tool_calls") or []:
            if c.get("name") != case["tool_name"]:
                continue
            args = c.get("arguments")
            blob = json.dumps(args, ensure_ascii=False).lower() \
                if not isinstance(args, str) else args.lower()
            if case["arg_substr"].lower() in blob:
                return True
        return False
    if kind == "vision_colors":
        d = _extract_json(text)
        if not isinstance(d, dict):
            return False
        left = str(d.get("left_color", "")).lower()
        right = str(d.get("right_color", "")).lower()
        return "red" in left and "blue" in right
    return None


# ---------------------------------------------------------------- targets --

def _meta(license_, data_policy, hardware, cost, notes=""):
    return {"license": license_, "data_policy": data_policy,
            "hardware_fit": hardware, "cost_class": cost, "notes": notes}


def targets(suite):
    L = []
    if suite in ("local", "all"):
        ollama_base = "http://127.0.0.1:11434/v1"
        for alias, model, vision in [
            ("ollama-omen-llama3.2-3b", "llama3.2:3b", False),
            ("ollama-omen-qwen3-4b", "qwen3:4b", False),
            ("ollama-omen-gemma3-4b", "gemma3:4b", True),
        ]:
            L.append({
                "suite": "local", "alias": alias, "provider": "openai",
                "base": ollama_base, "model": model,
                "api_key_env": None, "supports_vision": vision,
                "unload_cmd": ["ollama", "stop", model],
                "timeout": 180,
                "meta": _meta(
                    "model-card license; self-hosted, no third-party egress",
                    "local inference only — prompts never leave tony-omen",
                    "tony-omen Ollama (GPU-assisted); fits consumer GPU/CPU",
                    "electricity only; $0 marginal",
                    "cold call includes model load after `ollama stop`"),
            })
    if suite in ("remote", "all"):
        gw = "http://100.102.134.91:4000/v1"
        orbase = "https://openrouter.ai/api/v1"
        # -- idc03 local ollama (CPU tier) --------------------------------
        for alias, model, vision in [
            ("ollama-idc03-llama3.2-3b", "llama3.2:3b", False),
            ("ollama-idc03-moondream", "moondream", True),
        ]:
            L.append({
                "suite": "remote", "alias": alias, "provider": "openai",
                "base": "http://100.102.134.91:11434/v1", "model": model,
                "api_key_env": None, "supports_vision": vision,
                "unload_cmd": ["ollama", "stop", model],
                "timeout": 180,
                "meta": _meta(
                    "model-card license; self-hosted on idc03",
                    "local tailnet inference — no public egress",
                    "idc03 Ollama CPU tier; small models only",
                    "electricity only; $0 marginal",
                    "moondream is the vision leg on idc03"),
            })
        # -- Colab burst via LiteLLM tunnel alias --------------------------
        L.append({
            "suite": "remote", "alias": "colab-gemma3", "provider": "openai",
            "base": gw, "model": "colab-gemma3",
            "api_key_env": "LITELLM_KEY_CHABA", "supports_vision": False,
            "timeout": 60,
            "meta": _meta(
                "gemma license via Ollama; ephemeral Colab T4",
                "Colab egress only while VM lives; no durable state",
                "Colab T4 burst — route dies with session",
                "Colab free quota; $0 marginal",
                "tunnel was DOWN at probe time (403 model access)"),
        })
        # -- OpenRouter pinned :free ---------------------------------------
        or_free = [
            ("or-flint-v1.0-free", "recursive/flint-v1.0:free", False,
             {"prompt": 0.0, "completion": 0.0},
             "open-weight MoE (40B total / ~2.5B active); Recursive",
             "text->text, 262K ctx, tools+response_format",
             "pinned separately per card — do not fold into :free auto"),
            ("or-nemotron-3.5-super-vl-free",
             "nvidia/nemotron-3.5-super-vl:free", True,
             {"prompt": 0.0, "completion": 0.0},
             "NVIDIA Open Model license",
             "text+image+video->text, 1M ctx, tools",
             "vision-capable free leg"),
            ("or-nemotron-3.5-lightning-free",
             "nvidia/nemotron-3.5-lightning:free", False,
             {"prompt": 0.0, "completion": 0.0},
             "NVIDIA Open Model license",
             "text->text, 1M ctx, tools",
             "fast free leg"),
            ("or-laguna-s-2.1-free", "poolside/laguna-s-2.1:free", False,
             {"prompt": 0.0, "completion": 0.0},
             "Poolside license (see model card)",
             "code-focused free model",
             "prior scorecard 100 comp; may be delisted — 404 recorded if so"),
        ]
        for alias, model, vision, price, lic, hw, notes in or_free:
            L.append({
                "suite": "remote", "alias": alias, "provider": "openrouter",
                "base": orbase, "model": model,
                "api_key_env": "OPENROUTER_API_KEY",
                "supports_vision": vision, "timeout": 90,
                "price": price,
                "meta": _meta(
                    lic,
                    "OpenRouter :free — provider-dependent; OR account sees prompts",
                    hw, "free tier (OR :free daily cap ~1000 req/day)",
                    notes),
            })
        # -- DeepSeek V4.1 Flash as deepseek-flash --------------------------
        L.append({
            "suite": "remote", "alias": "deepseek-flash", "provider": "openrouter",
            "base": orbase, "model": "deepseek/deepseek-v4.1-flash",
            "api_key_env": "OPENROUTER_API_KEY", "supports_vision": True,
            "extra_payload": {"reasoning_effort": "low"},
            "timeout": 90,
            "price": {"prompt": 0.00000014, "completion": 0.00000042},
            "meta": _meta(
                "DeepSeek API terms (paid)",
                "sent to DeepSeek via OpenRouter; paid tier, no :free training assumption",
                "provider-hosted 1M-ctx multimodal MoE; tool+JSON capable",
                "paid: ~$0.14/M in, $0.42/M out (OR listing 2026-11-24)",
                "card asks to add V4.1 Flash as deepseek-flash; measured via OR "
                "because no DEEPSEEK_API_KEY exists on fleet; "
                "reasoning_effort=low so tiny max_tokens budgets return content"),
        })
        # -- official DeepSeek API (credentials likely absent) --------------
        L.append({
            "suite": "remote", "alias": "deepseek-flash-official",
            "provider": "openai", "base": "https://api.deepseek.com",
            "model": "deepseek-flash", "api_key_env": "DEEPSEEK_API_KEY",
            "supports_vision": True, "timeout": 90,
            "price": {"prompt": 0.0000003, "completion": 0.0000012},
            "meta": _meta(
                "DeepSeek API terms",
                "direct to DeepSeek; paid API",
                "official DeepSeek-V4.1-Flash-1017, 1M ctx, vision+tools",
                "paid: peak $0.30/M in, $1.20/M out; off-peak half",
                "DEEPSEEK_API_KEY not present on idc03/tony-dell/tony-omen — "
                "recorded as no_credentials if unset"),
        })
        # -- Gemini gateway vs direct ---------------------------------------
        L.append({
            "suite": "remote", "alias": "gemini-3.5-flash-lite-gateway",
            "provider": "openai", "base": gw, "model": "gemini-3.5-flash-lite",
            "api_key_env": "LITELLM_KEY_CHABA", "supports_vision": False,
            "timeout": 90,
            "meta": _meta(
                "Google Gemini API terms via LiteLLM",
                "via idc03 LiteLLM gateway; paid key upstream",
                "provider-hosted; gateway adds routing/fallback",
                "metered paid Gemini; spend on LITELLM_KEY_CHABA",
                "gateway leg — compare against direct"),
        })
        L.append({
            "suite": "remote", "alias": "gemini-3.5-flash-lite-direct",
            "provider": "gemini", "base": "https://generativelanguage.googleapis.com",
            "model": "gemini-3.5-flash-lite", "api_key_env": "GEMINI_API_KEY_PAID",
            "supports_vision": False, "timeout": 90,
            "meta": _meta(
                "Google Gemini API terms",
                "direct to Google; paid key",
                "provider-hosted",
                "metered paid Gemini",
                "direct leg — no gateway tax"),
        })
    return L


# ------------------------------------------------------------------ runner --

def _key(t):
    env = t.get("api_key_env")
    if not env:
        return None
    return os.environ.get(env)


def run_target(t, warm_repeats=WARM_REPEATS):
    alias = t["alias"]
    out = {"alias": alias, "provider": t["provider"], "model": t["model"],
           "suite": t["suite"], "fixture": FIXTURE, "meta": t.get("meta", {}),
           "api_key_env": t.get("api_key_env"),
           "cases": [], "warm": [], "status": "ok"}
    env = t.get("api_key_env")
    if env and not os.environ.get(env):
        out["status"] = "no_credentials"
        out["note"] = f"{env} not set — provider skipped"
        return out
    t = dict(t)
    t["key"] = _key(t)
    if t.get("unload_cmd"):
        try:
            subprocess.run(t["unload_cmd"], capture_output=True, timeout=20)
        except Exception:
            pass
        time.sleep(1.0)
    caller = CALLERS[t["provider"]]
    warm_case = CASES[0]
    first = True
    for case in CASES:
        if case.get("vision") and not t.get("supports_vision"):
            out["cases"].append({"name": case["name"], "skipped": "no_vision"})
            continue
        res = caller(t, case)
        ok = check_case(case, res) if res.get("ok") else False
        rec = {"name": case["name"], "ok": bool(res.get("ok")),
               "check_ok": ok, "s": round(res.get("s", 0), 3),
               "status": res.get("status"), "error": res.get("error"),
               "usage": res.get("usage"),
               "tool_calls": res.get("tool_calls") or None,
               "text_preview": (res.get("text") or "")[:160]}
        if res.get("resolved_model"):
            rec["resolved_model"] = res["resolved_model"]
        if res.get("error_detail"):
            rec["error_detail"] = res["error_detail"]
        out["cases"].append(rec)
        if first:
            for _ in range(warm_repeats):
                w = caller(t, warm_case)
                out["warm"].append({
                    "s": round(w.get("s", 0), 3), "ok": bool(w.get("ok")),
                    "status": w.get("status"), "error": w.get("error"),
                    "usage": w.get("usage")})
            first = False
        time.sleep(0.3)
    # aggregate
    lats = [c["s"] for c in out["cases"] if c.get("ok")]
    warm_lats = [w["s"] for w in out["warm"] if w.get("ok")]
    pt = sum((c.get("usage") or {}).get("prompt_tokens") or 0
             for c in out["cases"])
    ct = sum((c.get("usage") or {}).get("completion_tokens") or 0
             for c in out["cases"])
    tt = sum((c.get("usage") or {}).get("total_tokens") or 0
             for c in out["cases"])
    attempted = [c for c in out["cases"] if "ok" in c]
    errs = [c for c in attempted if not c["ok"]]
    e429 = [c for c in errs if c.get("status") == 429]
    checks = [c for c in attempted if "check_ok" in c]
    price = t.get("price") or {}
    cost = None
    if price and (pt or ct):
        cost = round(pt * float(price.get("prompt", 0)) +
                     ct * float(price.get("completion", 0)), 8)
    out["summary"] = {
        "cold_s": out["cases"][0].get("s") if out["cases"] else None,
        "case_p50_s": round(statistics.median(lats), 3) if lats else None,
        "warm_p50_s": round(statistics.median(warm_lats), 3)
        if warm_lats else None,
        "warm_n": len(warm_lats),
        "prompt_tokens": pt, "completion_tokens": ct,
        "total_tokens": tt,
        "errors": len(errs), "http_429": len(e429),
        "error_rate": round(len(errs) / max(1, len(attempted)), 3),
        "checks_passed": sum(1 for c in checks if c["check_ok"]),
        "checks_total": len(checks),
        "est_cost_usd": cost,
    }
    if errs and not any(c["ok"] for c in attempted):
        out["status"] = "all_failed"
    elif errs:
        out["status"] = "partial_errors"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["local", "remote", "all"],
                    default="all")
    ap.add_argument("--only", default=None,
                    help="substring filter on alias")
    ap.add_argument("--warm", type=int, default=WARM_REPEATS)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ts = targets(args.suite)
    if args.only:
        ts = [t for t in ts if args.only in t["alias"]]
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    runs = []
    for t in ts:
        print(f"[{started}] run {t['alias']} ({t['provider']}/{t['model']})",
              file=sys.stderr, flush=True)
        runs.append(run_target(t, args.warm))
    rep = {"fixture": FIXTURE, "suite": args.suite, "started": started,
           "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "warm_repeats": args.warm, "runs": runs}
    txt = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w") as f:
            f.write(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
