#!/usr/bin/env python3
"""promote-views.py — merge Lovelace views into a prod dashboard over websocket.

Two source modes:

  * dev -> prod (legacy):
        promote-views.py <dev_url> <prod_url> <dash_path> <views|all>
            [--create] [--dry-run]
    Tokens come from DEV_TOKEN / PROD_TOKEN env vars.

  * checked-in snapshot -> prod (used by Ansible):
        promote-views.py --file <snapshot.json> --view <paths>
            [--token-file <env-file>] [--create] [--dry-run]
            <prod_url> <dash_path>
    Views are read from the local JSON file instead of DEV. --token-file
    reads the long-lived token from a host-side 0600 env file, so it never
    enters the process arguments. Multiple view paths are comma-separated.

In both modes, views whose path already exists on prod are replaced, new
paths are appended, and prod-only views are preserved. When the merge would
not change anything the script prints `already current` and does not write —
that line is the idempotency signal Ansible's changed_when keys on.

--create registers the dashboard via lovelace/dashboards/create when missing.
--dry-run prints the plan (or `already current`) without writing.
"""
import asyncio
import json
import os
import pathlib
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


VALUE_FLAGS = {"--file", "--view", "--token-file"}
TOKEN_KEYS = ("HA_LONG_LIVED_TOKEN", "HASS_TOKEN", "HA_TOKEN", "SUPERVISOR_TOKEN")


def parse_args(argv):
    """Split argv into options and positional args, allowing flags with values."""
    opts, positional, i = {}, [], 0
    while i < len(argv):
        arg = argv[i]
        if arg in VALUE_FLAGS:
            if i + 1 >= len(argv):
                sys.exit(f"[promote-views] {arg} needs a value")
            opts[arg] = argv[i + 1]
            i += 2
        elif arg.startswith("--"):
            opts[arg] = True
            i += 1
        else:
            positional.append(arg)
            i += 1
    return opts, positional


def token_from_file(path):
    """Read a long-lived token from a KE=VALUE secret file (never argv)."""
    for line in pathlib.Path(path).read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() in TOKEN_KEYS:
            return value.strip().strip('"').strip("'")
    sys.exit(f"[promote-views] no HA token key in {path}")


async def main():
    opts, positional = parse_args(sys.argv[1:])
    create = "--create" in opts
    dry = "--dry-run" in opts

    if "--file" in opts:
        if len(positional) != 2:
            sys.exit("[promote-views] file mode needs <prod_url> <dash_path>")
        prod_url, path = positional
        want = opts.get("--view", "all")
        with open(opts["--file"], encoding="utf-8") as fh:
            cfg = json.load(fh)
        prod_token = (token_from_file(opts["--token-file"]) if "--token-file" in opts
                      else os.environ["PROD_TOKEN"])
    else:
        if len(positional) != 4:
            sys.exit("[promote-views] usage: <dev_url> <prod_url> <dash_path> "
                     "<views|all> [--create] [--dry-run]")
        dev_url, prod_url, path, want = positional
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
        assert create, \
            f"dashboard '{path}' missing on prod (pass --create to register it)"
        if dry:
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

    current = prod_cfg.get("views", [])
    by = {v.get("path"): i for i, v in enumerate(current)}
    replaced = [v.get("path") for v in sel if v.get("path") in by]
    added = [v.get("path") for v in sel if v.get("path") not in by]
    new_views = list(current)
    for v in sel:
        p = v.get("path")
        if p in by:
            new_views[by[p]] = v
        else:
            new_views.append(v)

    if new_views == current:
        print(f"already current: {sel_paths} on '{path}'")
        return
    if dry:
        print(f"DRY: dashboard '{path}' — replace views {replaced}, "
              f"add views {added} (prod keeps {len(by) - len(replaced)} "
              f"prod-only views)")
        return

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
