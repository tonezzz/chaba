#!/usr/bin/env python3
"""Probe service tiers, built-in tools and implicit caching on free tier.

Read-only, synthetic text only. Env: GEMINI_API_KEY, MODEL, OUT.
"""
import json
import os
import time
from datetime import datetime, timezone

from google import genai

MODEL = os.environ.get("MODEL", "gemini-3.5-flash-lite")
OUT = os.environ.get("OUT", "/tmp/opencode/g4-interactions-advanced.json")
client = genai.Client()
results = {}


def dump(obj):
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, (dict, list, str, int, float, bool)):
        return obj
    return str(obj)


def record(name, fn):
    t0 = time.monotonic()
    try:
        out = fn() or {}
        results[name] = {"ok": True, "elapsed_s": round(time.monotonic() - t0, 2), **out}
    except Exception as e:
        results[name] = {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:400]}",
            "elapsed_s": round(time.monotonic() - t0, 2),
        }
    r = results[name]
    print(name, "OK" if r["ok"] else "FAIL", str(r.get("error", ""))[:180], flush=True)


def tier(tier_name):
    r = client.interactions.create(
        model=MODEL, input="Reply with exactly: TIEROK", service_tier=tier_name)
    return {"id": getattr(r, "id", None),
            "text": str(getattr(r, "output_text", None))[:100],
            "service_tier": str(getattr(r, "service_tier", None)),
            "status": str(getattr(r, "status", None)),
            "usage": dump(getattr(r, "usage", None))}


def flex():
    return tier("flex")


def priority():
    return tier("priority")


def code_execution():
    r = client.interactions.create(
        model=MODEL,
        input="Use Python to compute the 20th Fibonacci number. Reply with the number only.",
        tools=[{"type": "code_execution"}])
    return {"id": getattr(r, "id", None),
            "text": str(getattr(r, "output_text", None))[:200],
            "steps": [str(getattr(s, "type", None)) for s in (getattr(r, "steps", None) or [])],
            "usage": dump(getattr(r, "usage", None))}


def google_search():
    r = client.interactions.create(
        model=MODEL,
        input="What is the capital of Japan? Answer in one word.",
        tools=[{"type": "google_search"}])
    return {"id": getattr(r, "id", None),
            "text": str(getattr(r, "output_text", None))[:200],
            "steps": [str(getattr(s, "type", None)) for s in (getattr(r, "steps", None) or [])],
            "usage": dump(getattr(r, "usage", None))}


PREFIX = ("The project registry records model names, latency budgets and tool policies. "
          "Each review cycle checks owners, rollout gates and rollback notes. ") * 240


def implicit_cache():
    out = []
    for suffix in ("What is the first topic in the registry? Reply in one word.",
                   "What is the second topic in the registry? Reply in one word."):
        r = client.interactions.create(
            model=MODEL, input=PREFIX + "\n" + suffix, store=False)
        u = dump(getattr(r, "usage", None)) or {}
        out.append({"suffix": suffix[:40], "text": str(getattr(r, "output_text", None))[:100],
                    "total_input_tokens": u.get("total_input_tokens"),
                    "total_cached_tokens": u.get("total_cached_tokens")})
    return {"prefix_chars": len(PREFIX), "calls": out}


def main():
    record("flex", flex)
    record("priority", priority)
    record("code_execution", code_execution)
    record("google_search", google_search)
    record("implicit_cache", implicit_cache)
    out = {"schema": "g4-interactions-advanced", "schema_version": 1,
           "date": datetime.now(timezone.utc).isoformat(), "host": "idc03",
           "model": MODEL, "key_printed": False, "results": results}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
