#!/usr/bin/env python3
"""promote-views.py — merge Lovelace views dev -> prod over websocket.

Usage:
    promote-views.py <dev_url> <prod_url> <dash_url_path> <views|all>
        [--create] [--dry-run]

Fetches the dashboard config from DEV (DEV_TOKEN env), selects views by
`path` (or all), then merges them into the PROD dashboard of the same
url_path (PROD_TOKEN env): views whose path already exists on prod are
replaced, new paths are appended — prod-only views are preserved.

--create registers the dashboard on prod via lovelace/dashboards/create when
it is missing (idempotent: requires_admin off, sidebar shown, title = path).
--dry-run prints the merge plan (which prod views would be replaced/added)
without writing.
"""
import asyncio
import json
import os
import sys

import websockets


async def ws_cmd(ws, payload, counter):
    counter[0] += 1
    payload["id"] = counter[0]
    await ws.send(json.dumps(payload))
    while True:
        r = json.loads(await ws.recv())
        if r.get("id") == counter[0]:
            return r


async def connect(url, token):
    ws_url = url.replace("http", "ws", 1) + "/api/websocket"
    ws = await websockets.connect(ws_url)
    counter = [0]
    await ws.recv()  # auth_required
    await ws.send(json.dumps({"type": "auth", "access_token": token}))
    r = json.loads(await ws.recv())
    assert r.get("type") == "auth_ok", r
    return ws, counter


async def get_config(url, token, path):
    ws, c = await connect(url, token)
    try:
        r = await ws_cmd(ws, {"type": "lovelace/config", "url_path": path}, c)
        return r.get("result") if r.get("success") else None
    finally:
        await ws.close()


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    dev_url, prod_url, path, want = args[0], args[1], args[2], args[3]
    dev_token, prod_token = os.environ["DEV_TOKEN"], os.environ["PROD_TOKEN"]

    cfg = await get_config(dev_url, dev_token, path)
    assert cfg, f"no dashboard '{path}' on dev"
    views = cfg.get("views", [])
    sel = views if want == "all" else \
        [v for v in views if v.get("path") in want.split(",")]
    missing = set(want.split(",")) - {v.get("path") for v in sel} \
        if want != "all" else set()
    assert not missing, f"dev views not found: {sorted(missing)}"
    sel_paths = [v.get("path") or v.get("title") for v in sel]

    prod_cfg = await get_config(prod_url, prod_token, path)
    if prod_cfg is None:
        assert "--create" in flags, \
            f"dashboard '{path}' missing on prod (pass --create to register it)"
        if "--dry-run" in flags:
            print(f"DRY: would create dashboard '{path}' on prod, "
                  f"then merge {len(sel)} views: {sel_paths}")
            return
        ws, c = await connect(prod_url, prod_token)
        r = await ws_cmd(ws, {"type": "lovelace/dashboards/create",
                              "url_path": path, "title": path.replace("-", " ").title(),
                              "icon": "mdi:view-dashboard",
                              "require_admin": False,
                              "show_in_sidebar": True}, c)
        assert r.get("success"), r
        prod_cfg = {"views": []}
        await ws.close()
        print(f"created dashboard '{path}' on prod")

    by = {v.get("path"): i for i, v in enumerate(prod_cfg.get("views", []))}
    replaced = [v.get("path") for v in sel if v.get("path") in by]
    added = [v.get("path") for v in sel if v.get("path") not in by]
    if "--dry-run" in flags:
        print(f"DRY: dashboard '{path}' — replace views {replaced}, "
              f"add views {added} (prod keeps {len(by) - len(replaced)} "
              f"prod-only views)")
        return

    new_views = list(prod_cfg.get("views", []))
    for v in sel:
        p = v.get("path")
        if p in by:
            new_views[by[p]] = v
        else:
            new_views.append(v)
    out_cfg = dict(prod_cfg)
    out_cfg["views"] = new_views

    ws, c = await connect(prod_url, prod_token)
    try:
        out = await ws_cmd(ws, {"type": "lovelace/config/save",
                                "url_path": path, "config": out_cfg}, c)
        assert out.get("success"), out
    finally:
        await ws.close()
    print(f"saved '{path}': replaced={replaced} added={added}")


try:
    asyncio.run(main())
except AssertionError as e:
    sys.exit(f"[promote-views] {e}")
except Exception as e:  # noqa: BLE001 — surface ws/auth failures as one line
    sys.exit(f"[promote-views] {type(e).__name__}: {e}")
