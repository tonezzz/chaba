#!/usr/bin/env python3
"""Time each stage of the Ada PWA flow end-to-end.

Stages:
  page_load     GET / (HTML shell)
  static_asset  biggest JS bundle the page references
  auth_session  POST /api/auth/session (api_key -> cookie)
  ws_connect    ws handshake -> 'ready' event (Gemini Live up)
  prime         ready -> first assistant transcript delta (primed greeting)
  answer_first  user text -> first assistant delta
  answer_full   user text -> response_completed
"""
import asyncio
import json
import sys
import time
import urllib.request
import urllib.parse
import http.cookiejar

import websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
KEY = sys.argv[2] if len(sys.argv) > 2 else ""
BASE = BASE.rstrip("/")


def t(label, t0):
    print(f"  {label:14s} {time.monotonic() - t0:7.2f}s", flush=True)


def main():
    t0 = time.monotonic()
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(BASE + "/", headers={"User-Agent": "timing-probe"})
    html = op.open(req, timeout=20).read().decode("utf-8", "replace")
    t("page_load", t0)

    t0 = time.monotonic()
    import re
    js = re.findall(r'src="([^"]+\.js[^"]*)"', html)
    if js:
        op.open(urllib.request.Request(urllib.parse.urljoin(BASE + '/', js[0])), timeout=20).read()
    t("static_asset", t0)

    t0 = time.monotonic()
    r = op.open(urllib.request.Request(
        BASE + "/api/auth/session",
        data=json.dumps({"api_key": KEY}).encode(),
        headers={"Content-Type": "application/json"}), timeout=20)
    json.loads(r.read())
    t("auth_session", t0)

    asyncio.run(ws_part())


async def ws_part():
    t0 = time.monotonic()
    ws_url = BASE.replace("http", "ws") + "/ws?api_key=" + KEY
    ws = await websockets.connect(ws_url, max_size=8 * 1024 * 1024)
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=60)
        if isinstance(raw, bytes):
            continue
        msg = json.loads(raw)
        if msg.get("type") == "ready":
            break
    t("ws_connect", t0)

    # primed greeting: first assistant transcript delta after ready
    t0 = time.monotonic()
    first_delta = None
    done = False
    try:
        while not done:
            raw = await asyncio.wait_for(ws.recv(), timeout=240)
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            ty = msg.get("type")
            if ty == "assistant_transcript_delta" and first_delta is None:
                first_delta = time.monotonic() - t0
            if ty == "response_completed":
                done = True
    except asyncio.TimeoutError:
        print("  prime_full     (timeout)", flush=True)
    if first_delta:
        print(f"  prime_first    {first_delta:7.2f}s", flush=True)
    if done:
        t("prime_full", t0)

    # a fresh question: first token + full answer
    await ws.send(json.dumps({"type": "text", "text": "Quick check: what is 2+2?"}))
    t0 = time.monotonic()
    first = None
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=120)
        if isinstance(raw, bytes):
            continue
        msg = json.loads(raw)
        ty = msg.get("type")
        if ty == "assistant_transcript_delta" and first is None:
            first = time.monotonic() - t0
            print(f"  answer_first   {first:7.2f}s", flush=True)
        if ty == "response_completed":
            t("answer_full", t0)
            break
    await ws.close()


if __name__ == "__main__":
    main()
