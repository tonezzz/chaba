#!/usr/bin/env python3
"""Copy a Lovelace view between Home Assistant instances.

Usage:
    SRC_TOKEN=<token> DST_TOKEN=<token> copy-view.py <src_url> <dst_url> <view_path> [--first|--after <path>]

Example (dev -> ha, pfg2 as first tab):
    export SRC_TOKEN=$(grep HASS_TOKEN ~/.config/secrets/ha-michael-dev.env | cut -d= -f2)
    export DST_TOKEN=$(cat ~/.local/share/home-assistant-michael/ha-token)
    copy-view.py https://tony-dell.taila0626a.ts.net:8124 http://michael-ha:8123 pfg2 --first

Notes:
- On michael-ha the visionos theme injects a frosted-glass ha-card::before; this
  script re-adds the card_mod override to any card that has pfg_transparent.
"""
import asyncio, json, os, sys
import websockets

SRC_URL, DST_URL, VIEW = sys.argv[1], sys.argv[2], sys.argv[3]
FIRST = "--first" in sys.argv
AFTER = sys.argv[sys.argv.index("--after") + 1] if "--after" in sys.argv else None
DASH = sys.argv[sys.argv.index("--dash") + 1] if "--dash" in sys.argv else "tony-test"

CARD_MOD = {"style": "ha-card::before { content: none !important; } "
                     "ha-card { background: transparent !important; box-shadow: none !important; }"}

async def ws(url, token):
    c = await websockets.connect(url.replace("http", "ws", 1) + "/api/websocket")
    await c.recv()
    await c.send(json.dumps({"type": "auth", "access_token": token}))
    assert json.loads(await c.recv())["type"] == "auth_ok"
    return c

async def cmd(w, p):
    cmd.i = getattr(cmd, "i", 1) + 1
    p["id"] = cmd.i
    await w.send(json.dumps(p))
    while True:
        r = json.loads(await w.recv())
        if r.get("id") == cmd.i:
            return r

async def main():
    src = await ws(SRC_URL, os.environ["SRC_TOKEN"])
    dst = await ws(DST_URL, os.environ["DST_TOKEN"])
    s = (await cmd(src, {"type": "lovelace/config", "url_path": DASH}))["result"]
    d = (await cmd(dst, {"type": "lovelace/config", "url_path": DASH}))["result"]
    v = next(x for x in s["views"] if x.get("path") == VIEW)

    for card in v.get("cards", []):
        if card.get("pfg_transparent") and "card_mod" not in card:
            card["card_mod"] = CARD_MOD

    d["views"] = [x for x in d["views"] if x.get("path") != VIEW]
    if FIRST:
        d["views"].insert(0, v)
    elif AFTER:
        i = next((n for n, x in enumerate(d["views"]) if x.get("path") == AFTER), len(d["views"]) - 1)
        d["views"].insert(i + 1, v)
    else:
        d["views"].append(v)
    out = await cmd(dst, {"type": "lovelace/config/save", "url_path": DASH, "config": d})
    print("saved:", out.get("success"), "| order:", [x.get("path") for x in d["views"]])

asyncio.run(main())
