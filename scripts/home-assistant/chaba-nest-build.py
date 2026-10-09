#!/usr/bin/env python3
"""Build + push the chaba-nest dashboard on ada-ha from its SSOT spec.

    python3 scripts/home-assistant/chaba-nest-build.py [--print] [--apply]
        [--ha http://127.0.0.1:8125] [--spec PATH]

Spec: docs/ssot/infrastructure/ssot.chaba-nest-dashboard.yml (the modular
single source — topics, tile slugs, report filters, zoom/aspect).

Auth: ada-ha has no HASS_TOKEN file; the refresh token named 'tony-devin' in
~/.config/ada-ha/.storage/auth is exchanged at /auth/token, then websocket
auth. The CMS viewer api_key is reused from the live dashboard config (or
CMS_API_KEY env / ~/.config/secrets/ada-ha-cms.env CMS_API_KEY= line).

Layout generated per topic (TILE STANDARD — tiles never scroll):
    <path>          type=masonry: markdown nav pill + one ?card=1&zoom=…
                    iframe tile per slug
    <path>-reports  subview:true + back_path, type=panel iframe to the
                    full CMS browser pre-filtered (tab=/q= params)
"""
import asyncio, json, os, re, sys
import websockets, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, "docs/ssot/infrastructure/ssot.chaba-nest-dashboard.yml")
HA = "http://127.0.0.1:8125"


def load_spec(path):
    return yaml.safe_load(open(path))


def get_access_token(ha):
    """refresh_token 'tony-devin' → access_token via /auth/token."""
    import urllib.request
    auth = json.load(open(os.path.expanduser("~/.config/ada-ha/.storage/auth")))
    rt = next(t["token"] for t in auth["data"]["refresh_tokens"]
              if t.get("client_name") == "tony-devin")
    req = urllib.request.Request(
        ha + "/auth/token", method="POST",
        data=f"grant_type=refresh_token&refresh_token={rt}".encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req))["access_token"]


def cms_key(live_config):
    """Reuse the viewer api_key already embedded in the live dashboard."""
    env = os.environ.get("CMS_API_KEY")
    if env:
        return env
    for src in (os.path.expanduser("~/.config/secrets/ada-ha-cms.env"),):
        if os.path.exists(src):
            m = re.search(r"^CMS_API_KEY=(.+)$", open(src).read(), re.M)
            if m:
                return m.group(1).strip()
    txt = json.dumps(live_config or {})
    m = re.search(r"api_key=([A-Za-z0-9_\-]+)", txt)
    if m:
        return m.group(1)
    raise SystemExit("no CMS api_key found — set CMS_API_KEY or save once")


def build_views(spec, key):
    cms = f"{spec['dashboard']['cms_base']}?api_key={key}"
    zoom, ratio = spec["dashboard"]["zoom"], spec["dashboard"]["tile_aspect"]
    views = []
    for t in spec["topics"]:
        name, path = t["name"], t["path"]
        pill = {"type": "markdown", "content":
                f"**{name}**  ·  [All reports →](/{spec['dashboard']['url_path']}/{path}-reports)  ·  "
                "filter: the Reports view has the live filter box"}
        tiles = [{"type": "iframe", "aspect_ratio": ratio,
                  "url": f"{cms}&card=1&zoom={zoom}#/{s}"}
                 for s in t["tiles"]]
        views.append({"title": name, "path": path, "type": "masonry",
                      "cards": [pill] + tiles})
        views.append({"title": f"{name} — Reports", "path": f"{path}-reports",
                      "subview": True, "back_path": f"/{spec['dashboard']['url_path']}/{path}",
                      "type": "panel",
                      "cards": [{"type": "iframe", "aspect_ratio": "0%",
                                 "url": f"{cms}&{t['reports']}"}]})
    return views


async def main():
    args = sys.argv[1:]
    ha = args[args.index("--ha") + 1] if "--ha" in args else HA
    spec = load_spec(args[args.index("--spec") + 1] if "--spec" in args else SPEC)
    token = get_access_token(ha)
    ws_url = ha.replace("http", "ws", 1) + "/api/websocket"
    async with websockets.connect(ws_url) as ws:
        i = 0
        async def cmd(payload):
            nonlocal i
            i += 1
            payload["id"] = i
            await ws.send(json.dumps(payload))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == i:
                    return r
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        r = json.loads(await ws.recv())
        assert r.get("type") == "auth_ok", r
        r = await cmd({"type": "lovelace/config",
                       "url_path": spec["dashboard"]["url_path"]})
        live = r.get("result") if r.get("success") else None
        views = build_views(spec, cms_key(live))
        if "--print" in args:
            print(json.dumps({"views": views}, indent=2))
            return
        if "--apply" in args:
            r = await cmd({"type": "lovelace/config/save",
                           "url_path": spec["dashboard"]["url_path"],
                           "config": {"views": views}})
            assert r.get("success"), r
            print(f"saved {spec['dashboard']['url_path']} — {len(views)} views")
            return
        print("dry run — pass --print or --apply")


asyncio.run(main())
