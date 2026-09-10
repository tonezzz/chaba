#!/usr/bin/env python3
"""Apply non-Devices views from ~/.config/home-assistant/lovelace-dossier.yaml to the live Tony HA dashboard.

The live `devices` view is preserved from the existing dashboard so the
SSOT-generated table is not overwritten. Any view in live that is not in the
YAML is removed (e.g. a deleted YouTube tab).

Usage:
    python3 scripts/home-assistant/push-dossier-from-yaml.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import websockets
import yaml

HA_URL = "ws://tony-dell:8123/api/websocket"
TOKEN_FILE = Path.home() / ".config" / "secrets" / "home-assistant-token.env"
YAML_FILE = Path.home() / ".config" / "home-assistant" / "lovelace-dossier.yaml"


def load_token() -> str:
    text = TOKEN_FILE.read_text().strip()
    for line in text.splitlines():
        m = re.match(r"^HA_LONG_LIVED_TOKEN=(.+)$", line.strip())
        if m:
            return m.group(1)
    raise ValueError(f"HA_LONG_LIVED_TOKEN not found in {TOKEN_FILE}")


async def main() -> int:
    token = load_token()
    local = yaml.safe_load(YAML_FILE.read_text(encoding="utf-8"))

    async with websockets.connect(HA_URL) as ws:
        async def cmd(payload: dict) -> dict:
            cmd.i = getattr(cmd, "i", 1) + 1
            payload["id"] = cmd.i
            await ws.send(json.dumps(payload))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == cmd.i:
                    return r

        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"HA auth failed: {auth}")

        resp = await cmd({"type": "lovelace/config", "url_path": "dossier"})
        live = resp.get("result") or {"title": "Dossier", "views": []}

    live_views_by_path = {v.get("path"): v for v in live.get("views", [])}
    new_views: list[dict] = []
    for v in local.get("views", []):
        path = v.get("path")
        if path == "devices":
            # Keep the live devices view (will be refreshed by build-dossier-devices.py)
            new_views.append(live_views_by_path.get("devices") or v)
        else:
            new_views.append(v)

    config = {"title": local.get("title", live.get("title", "Dossier")), "views": new_views}

    async with websockets.connect(HA_URL) as ws:
        async def cmd(payload: dict) -> dict:
            cmd.i = getattr(cmd, "i", 1) + 1
            payload["id"] = cmd.i
            await ws.send(json.dumps(payload))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == cmd.i:
                    return r

        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"HA auth failed: {auth}")

        save_resp = await cmd({"type": "lovelace/config/save", "url_path": "dossier", "config": config})
        if save_resp.get("success"):
            print(f"Pushed {len(new_views)} views to tony-ha Dossier")
        else:
            print(f"Save failed: {save_resp}")
            return 1
    return 0


if __name__ == "__main__":
    import asyncio
    raise SystemExit(asyncio.run(main()))
