#!/usr/bin/env python3
"""Update a lovelace resource URL on a storage-mode HA instance via websocket.
Usage:
    ws-resource-url.py <ha_url> <url_substring_to_match> <new_filename>

Finds the first resource whose url contains the match string and rewrites it
to /local/<new_filename>. Reads token from HASS_TOKEN env.
"""
import asyncio
import json
import os
import sys

import websockets


async def main():
    url, match, new_file = sys.argv[1], sys.argv[2], sys.argv[3]
    token = os.environ["HASS_TOKEN"]
    ws_url = url.replace("http", "ws", 1) + "/api/websocket"
    async with websockets.connect(ws_url) as ws:

        async def cmd(p):
            cmd.i = getattr(cmd, "i", 1) + 1
            p["id"] = cmd.i
            await ws.send(json.dumps(p))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == cmd.i:
                    return r

        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        r = json.loads(await ws.recv())
        assert r.get("type") == "auth_ok", r
        res = await cmd({"type": "lovelace/resources"})
        assert res.get("success"), res
        target = next((x for x in res["result"] if match in x.get("url", "")), None)
        assert target, f"no lovelace resource matching {match!r}"
        new_url = f"/local/{new_file}"
        if target["url"] == new_url:
            print(f"already {new_url}")
            return
        out = await cmd(
            {
                "type": "lovelace/resources/update",
                "resource_id": target["id"],
                "res_type": target.get("res_type", target.get("type", "module")),
                "url": new_url,
            }
        )
        assert out.get("success"), out
        print(f"{target['url']} -> {new_url}")


asyncio.run(main())
