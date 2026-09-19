#!/usr/bin/env python3
"""Copy TPL-tab card templates onto tiles of another view (e.g. pfg2).

Each TPL card is a single-tile template keyed "1,1" (pfg_charts/pfg_images/
pfg_labels/pfg_value_labels/pfg_spans). This script copies those maps onto the
target view at the cells given by --map, then saves the whole dashboard.

Usage:
    apply-tpl.py <ha_url> <dashboard_path> <src_view> <dst_view> \\
        --map "TPLTitle:r,c;Title:r,c ..." [--dry-run] [--bg]

    --bg forces every copied chart def to position: 'bg' (background layer).
    (pairs separated by ';' since cells contain commas)

Example:
    apply-tpl.py https://tony-dell.taila0626a.ts.net:8124 tony-test tpl pfg2 \\
        --map "Grid:1,7;Battery:5,1;Home:5,7;Inverter:3,4;Sum:3,1"

Reads token from HASS_TOKEN env (source ~/.config/secrets/ha-michael-dev.env).
"""
import asyncio, copy, json, os, sys
import websockets

# pfg_spans intentionally excluded: TPL cards are single 2x2 tiles; copying the
# span would shrink the target tile.
MAP_KEYS = ("pfg_charts", "pfg_images", "pfg_labels", "pfg_value_labels",
            "pfg_radius", "pfg_border", "pfg_image_fit",
            "pfg_label_pos")

async def main():
    url, dash, src_view, dst_view = sys.argv[1:5]
    mapping = []  # list, not dict — the same TPL title may map to several cells
    if "--map" in sys.argv:
        for pair in sys.argv[sys.argv.index("--map") + 1].split(";"):
            t, cell = pair.split(":", 1)
            mapping.append((t.strip(), cell.strip()))
    dry = "--dry-run" in sys.argv
    bg = "--bg" in sys.argv
    token = os.environ["HASS_TOKEN"]

    async with websockets.connect(url.replace("http", "ws", 1) + "/api/websocket") as ws:
        async def cmd(payload):
            cmd.i = getattr(cmd, "i", 1) + 1
            payload["id"] = cmd.i
            await ws.send(json.dumps(payload))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == cmd.i:
                    return r
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"

        cfg = (await cmd({"type": "lovelace/config", "url_path": dash}))["result"]
        views = {v["path"]: v for v in cfg["views"] if "path" in v}
        tpl = {c.get("title"): c for c in views[src_view]["cards"]}
        dst = views[dst_view]["cards"][0]

        for title, cell in mapping:
            t = tpl.get(title)
            if not t:
                print(f"  !! no TPL card titled '{title}' — skipped")
                continue
            for k in MAP_KEYS:
                src = t.get(k, {})
                val = src.get("1,1") if isinstance(src, dict) else None
                if val is not None:
                    val = copy.deepcopy(val)
                    if k == "pfg_charts" and bg:
                        defs = val if isinstance(val, list) else [val]
                        for d in defs:
                            if isinstance(d, dict):
                                d["position"] = "bg"
                    dst.setdefault(k, {})[cell] = val
            print(f"  {title} -> {cell}{' [bg]' if bg else ''}")

        if not dry:
            out = await cmd({"type": "lovelace/config/save",
                             "url_path": dash, "config": cfg})
            print("saved:", out.get("success"))

asyncio.run(main())
