#!/usr/bin/env python3
"""Push live michael-ha states into michael-dev (replaces 30s REST polling).

Subscribes to state_changed on michael-ha over websocket and POSTs each
changed entity's state to michael-dev's /api/states/<entity_id>. Only
entities listed in the dev-mocks rest: mirror set are pushed.

Run on tony-dell as systemd user service mha-state-push.service.
Tokens:
  HA_TOKEN  (michael-ha)   ~/.local/share/home-assistant-michael/ha-token
  DEV_TOKEN (michael-dev)  ~/.config/secrets/ha-michael-dev.env  (HASS_TOKEN=)
"""
import asyncio
import json
import os
import re
import ssl
import urllib.request

import websockets

HA_URL = os.environ.get("HA_URL", "http://michael-ha:8123")
DEV_URL = os.environ.get("DEV_URL", "http://127.0.0.1:8124")
MOCKS = os.environ.get(
    "MOCKS", "/home/tony/.config/michael-dev/packages/a_dev_mocks.yaml"
)


def token(path, envs):
    for e in envs:
        if os.environ.get(e):
            return os.environ[e]
    try:
        for line in open(os.path.expanduser(path)):
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                if k in ("HASS_TOKEN", "HA_TOKEN", "DEV_TOKEN"):
                    return v.strip().strip("\"'")
            elif line:
                return line
    except OSError:
        pass
    return None


def mirror_ids():
    ids = set()
    for m in re.finditer(
        r"resource:\s*\S+/api/states/([a-z_]+\.[a-z0-9_]+)",
        open(MOCKS).read(),
    ):
        ids.add(m.group(1))
    return ids


def push(dev_token, entity_id, state, attrs):
    body = json.dumps(
        {"state": state, "attributes": attrs or {}}
    ).encode()
    req = urllib.request.Request(
        f"{DEV_URL}/api/states/{entity_id}",
        data=body,
        headers={
            "Authorization": f"Bearer {dev_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print(f"push fail {entity_id}: {e}", flush=True)


async def main():
    ha_token = token(
        "~/.local/share/home-assistant-michael/ha-token", ["HA_TOKEN"]
    )
    dev_token = token(
        "~/.config/secrets/ha-michael-dev.env", ["DEV_TOKEN", "HASS_TOKEN"]
    )
    ids = mirror_ids()
    print(f"mirroring {len(ids)} entity ids", flush=True)
    ws_url = HA_URL.replace("http", "ws", 1) + "/api/websocket"
    backoff = 5
    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                i = [0]

                async def cmd(p):
                    i[0] += 1
                    p["id"] = i[0]
                    await ws.send(json.dumps(p))
                    while True:
                        r = json.loads(await ws.recv())
                        if r.get("id") == i[0]:
                            return r

                await ws.recv()
                await ws.send(
                    json.dumps({"type": "auth", "access_token": ha_token})
                )
                auth = json.loads(await ws.recv())
                if auth.get("type") != "auth_ok":
                    raise RuntimeError(f"ha auth failed: {auth}")
                await cmd(
                    {
                        "type": "subscribe_events",
                        "event_type": "state_changed",
                    }
                )
                print("subscribed to state_changed", flush=True)
                backoff = 5
                while True:
                    ev = json.loads(await ws.recv())
                    d = ev.get("event", {}).get("data", {})
                    eid = d.get("entity_id")
                    new = d.get("new_state")
                    if not eid or eid not in ids or not new:
                        continue
                    push(dev_token, eid, new["state"], new.get("attributes"))
        except Exception as e:
            print(f"bridge error: {e}; retry in {backoff}s", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)


if __name__ == "__main__":
    asyncio.run(main())
