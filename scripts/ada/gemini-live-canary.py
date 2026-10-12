#!/usr/bin/env python3
"""gemini-live-canary — measure the free-tier Live quota by spending the
minimum possible: open one Gemini Live session, close immediately, log
the verdict. One connect per run; run hourly via ada-live-canary.timer.

Why: 2026-10-12 the paid project hit 402 'prepayment credits depleted'
after ~936 billed connects/day (scenario-spend-guard). To move scenario
runs onto the FREE lane safely we need the real ceiling — which Google
does not publish per-project. This probe maps it incrementally:

    ledger: ~/.local/share/ada-live-canary.jsonl  (one JSON line/run)
    verdicts: ok | quota(429) | credit(402/1011) | demand(503) | other
    journal: one INFO line per run (journald -> spend-report picks it up)

Read the ledger to find the ceiling: the hour/day where 'quota' verdicts
start is the measured max. Scenario budget should sit ~50% below it
(the free lane also serves production fallback — reserve headroom).

Usage:
  gemini-live-canary.py --env-file ~/.config/secrets/gemini-keys.env
                        --key-var GEMINI_API_KEY_FREE
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

MODEL = "gemini-3.1-flash-live-preview"
LEDGER = Path.home() / ".local/share/ada-live-canary.jsonl"


def _env_key(path: str, var: str) -> str:
    for line in Path(path).expanduser().read_text().splitlines():
        if line.startswith(var + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _verdict(exc: Exception) -> str:
    m = str(exc)
    if "429" in m or "RESOURCE_EXHAUSTED" in m or "quota" in m.lower():
        return "quota"
    if "1011" in m or "402" in m or "credits are depleted" in m.lower():
        return "credit"
    if "503" in m or "high demand" in m.lower():
        return "demand"
    if "401" in m or "403" in m or "API key" in m:
        return "auth"
    return "other"


async def probe(key: str) -> dict:
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        cfg = types.LiveConnectConfig(response_modalities=["AUDIO"])
        async with asyncio.timeout(20):
            async with client.aio.live.connect(model=MODEL, config=cfg):
                pass  # connect succeeded — close immediately
        return {"verdict": "ok"}
    except Exception as e:
        return {"verdict": _verdict(e), "detail": str(e)[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--key-var", default="GEMINI_API_KEY_FREE")
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    args = ap.parse_args()

    key = _env_key(args.env_file, args.key_var)
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    if not key:
        rec = {"verdict": "no-key"}
    else:
        try:
            rec = asyncio.run(probe(key))
        except Exception as e:
            rec = {"verdict": _verdict(e), "detail": str(e)[:200]}
    rec.update({"ts": ts, "key_var": args.key_var,
                "key_suffix": key[-4:] if key else ""})
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"gemini-live-canary: {rec['verdict']} "
          f"key=...{rec['key_suffix']} {rec.get('detail','')}")
    return 0 if rec["verdict"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
