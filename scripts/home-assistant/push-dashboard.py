#!/usr/bin/env python3
"""Push a lovelace dashboard config to a storage-mode HA instance via the
websocket API (no restart required). Usage:
    push-dashboard.py <ha_url> <dashboard_url_path> [--mutate PYFILE]

Reads token from HASS_TOKEN env (source ~/.config/secrets/ha-michael-dev.env).
If --mutate is given, it must define `mutate(config)` applied before saving.
"""
import asyncio, json, os, sys
import websockets

async def main():
    url, path = sys.argv[1], sys.argv[2]
    mutate_src = None
    if "--mutate" in sys.argv:
        mutate_src = open(sys.argv[sys.argv.index("--mutate") + 1]).read()
    token = os.environ["HASS_TOKEN"]
    ws_url = url.replace("http", "ws", 1) + "/api/websocket"
    async with websockets.connect(ws_url) as ws:
        async def cmd(payload):
            nonlocal_id = cmd.i = getattr(cmd, "i", 1) + 1
            payload["id"] = nonlocal_id
            await ws.send(json.dumps(payload))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == nonlocal_id:
                    return r
        await ws.recv()  # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        r = json.loads(await ws.recv())
        assert r.get("type") == "auth_ok", r
        cfg = await cmd({"type": "lovelace/config", "url_path": path})
        assert cfg.get("success"), cfg
        config = cfg["result"]
        if mutate_src:
            ns = {}
            exec(mutate_src, ns)
            ns["mutate"](config)
        out = await cmd({"type": "lovelace/config/save", "url_path": path, "config": config})
        assert out.get("success"), out
        print("saved", path)

asyncio.run(main())
