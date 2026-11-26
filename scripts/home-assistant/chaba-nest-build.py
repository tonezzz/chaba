#!/usr/bin/env python3
"""Build + push the chaba-nest dashboard on ada-ha from its SSOT spec.

    python3 scripts/home-assistant/chaba-nest-build.py [--print] [--apply]
        [--ha http://127.0.0.1:8125] [--spec PATH]

    Discovery lifecycle (human-gated — badge standard):
        --discover            query CMS pages, print tile candidates per topic
        --discover --propose  write candidates into spec as state: proposed
        --discover --auto-add N  auto-add candidates matching for >=N days
                              (state: auto — still badged; default gate stays human)
        --accept <slug>       pin a tile (state: pinned) wherever it appears
        --reject <slug>       drop a tile from all topics
        then --apply to push, commit the spec, sync SSOT->MDDB.

Spec: docs/ssot/infrastructure/ssot.chaba-nest-dashboard.yml (the modular
single source — topics, tile slugs/states, report filters, zoom/aspect).

Auth: ada-ha has no HASS_TOKEN file; the refresh token named 'ada-ha-live' in
~/.config/ada-ha/.storage/auth is exchanged at /auth/token, then websocket
auth. The CMS viewer api_key is reused from the live dashboard config (or
CMS_API_KEY env / ~/.config/secrets/ada-ha-cms.env CMS_API_KEY= line).

Layout generated per topic (TILE STANDARD — tiles never scroll):
    <path>          type=masonry: markdown nav pill + one ?card=1&zoom=…
                    iframe tile per slug (badged tiles get badge/why/opts)
    <path>-reports  subview:true + back_path, type=panel iframe to the
                    full CMS browser pre-filtered (tab=/q= params)
"""
import argparse, asyncio, datetime, json, os, re, sys, urllib.parse, urllib.request
from ada_ha_auth import get_access_token
import websockets, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, "docs/ssot/infrastructure/ssot.chaba-nest-dashboard.yml")
HA = "http://127.0.0.1:8125"
DEVICE_ID = "chaba-nest-build"

BADGE_OPTS = "pin: --accept {slug}  ·  drop: --reject {slug}  ·  decide via spec edit"

# ── Fleet telemetry view templates ──────────────────────────────────────
# extra_views entries may use `template: host_fleet|service_fleet` — expanded
# here into the same entities cards as tony-ha's lovelace.chaba_admin
# hosts/services views. The entity ids exist on ada-ha via the
# telemetry-ha-push-ada mirror job (ssot.jobs.yml), so cards render natively
# instead of iframing the CF-Access-gated tony-ha dashboards.
FLEET_HOSTS = ["kk_mac", "tony_omen", "tony_macbook", "tony_dell",
               "idc02", "idc03", "mn01", "con01"]
SVC_ORDER = ["kk_mac", "tony_dell", "tony_omen", "idc02", "idc03",
             "con01", "mn01", "tony_macbook"]
_TEMPS = {"kk_mac", "tony_omen", "tony_macbook", "tony_dell", "mn01"}
_NET = set(FLEET_HOSTS) - {"kk_mac"}
_BATTERY = {
    "tony_omen": ["battery_level", "battery_state"],
    "tony_macbook": ["battery_level", "battery_state", "battery_health",
                     "battery_voltage", "battery_cycles"],
}


# icon-density tweak carried over from the tony-ha source cards
_CARD_MOD = {"card_mod": {"style":
    "\n    ha-entity {\n      --paper-item-icon-prefix-width: 30px;\n    }\n"
    "    state-icon {\n      margin-inline-end: 2px;\n    }\n"}}


def _row(dev, suffix, name=None, domain="sensor"):
    return {"entity": f"{domain}.{dev}_{suffix}",
            "name": name or suffix.replace("_", " ")}


def _host_card(dev):
    ents = [{"type": "section", "label": "Vitals"}]
    if dev == "tony_macbook":
        ents.append(_row(dev, "battery_temp"))
    ents.append(_row(dev, "online", domain="binary_sensor"))
    ents += [_row(dev, k) for k in ("load", "mem", "disk")]
    if dev in _TEMPS:
        ents.append(_row(dev, "temps"))
    ents.append(_row(dev, "swap"))
    ents.append({"type": "section", "label": "Detail"})
    ents += [_row(dev, k) for k in _BATTERY.get(dev, [])]
    ents += [_row(dev, "uptime"), _row(dev, "users")]
    if dev in _NET:
        ents += [_row(dev, "net_rx"), _row(dev, "net_tx")]
    ents += [_row(dev, "top_proc"), _row(dev, "wan_city"),
             _row(dev, "wan_country"), _row(dev, "wan_org", "wan isp")]
    return {"type": "entities", "title": dev.replace("_", "-"),
            "entities": ents, **_CARD_MOD}


def _fleet_summary():
    ids = ([f"binary_sensor.{d}_online" for d in FLEET_HOSTS]
           + [f"sensor.{d}_{k}" for d in FLEET_HOSTS
              for k in ("load", "mem", "disk", "swap", "temps")])
    tpl = ("| sync | host | online | load | mem | disk | swap | temps |\n"
           "|---|---|---|---|---|---|---|---|\n"
           "{% for d in [" + ",".join(repr(d) for d in FLEET_HOSTS) + "] %}"
           "{% set ls = state_attr('sensor.'~d~'_load','last_seen') %}"
           "| {{ ls[:10].replace('-','') ~ '-' ~ ls[11:16] if ls else '—' }} "
           "| {{ d.replace('_','-') }} "
           "| {{ 'on' if is_state('binary_sensor.'~d~'_online','on') and is_state('binary_sensor.'~d~'_telemetry_fresh','on') else 'off' }} "
           "| {{ states('sensor.'~d~'_load') }} "
           "| {{ states('sensor.'~d~'_mem') }}% "
           "| {{ states('sensor.'~d~'_disk') }}% "
           "| {{ states('sensor.'~d~'_swap') }}% "
           "| {{ states('sensor.'~d~'_temps') if states('sensor.'~d~'_temps') "
           "not in ['unknown','unavailable'] else '—' }} |\n"
           "{% endfor %}")
    return {"type": "markdown",
            "title": "Host fleet — telemetry mirror (5min)",
            "entity_id": ids, "content": tpl}


def _svc_card(dev):
    ents = [{"type": "section", "label": "Vitals"},
            _row(dev, "online", domain="binary_sensor"),
            _row(dev, "uptime"),
            {"type": "section", "label": "Chaba"},
            _row(dev, "svc_device_telemetry", "device-telemetry",
                 domain="binary_sensor"),
            _row(dev, "top_proc", "watching")]
    if dev == "kk_mac":
        ents += [{"type": "section", "label": "DevNest"},
                 _row(dev, "svc_nest_worker", "nest-worker",
                      domain="binary_sensor"),
                 _row(dev, "svc_nest_worker_pending", "pending"),
                 _row(dev, "svc_nest_worker_job", "job")]
    elif dev != "tony_macbook":
        ents += [{"type": "section", "label": "DevNest"},
                 _row(dev, "svc_nest_mgr", "nest-mgr",
                      domain="binary_sensor"),
                 _row(dev, "svc_nest_mgr_nodes", "nodes"),
                 _row(dev, "svc_nest_mgr_active", "active")]
    return {"type": "entities", "title": dev.replace("_", "-"),
            "entities": ents, **_CARD_MOD}


def _expand_template(v):
    tpl = v.pop("template", None)
    if tpl == "host_fleet":
        v.setdefault("cards", [_fleet_summary()]
                     + [_host_card(d) for d in FLEET_HOSTS])
    elif tpl == "service_fleet":
        v.setdefault("cards", [_svc_card(d) for d in SVC_ORDER])
    if tpl:
        v.setdefault("type", "masonry")
    return v


def load_spec(path):
    return yaml.safe_load(open(path))


def save_spec(spec, path):
    """Rewrite spec preserving the leading comment block."""
    head = []
    for line in open(path):
        if line.strip().startswith("#") or not line.strip():
            head.append(line)
        else:
            break
    body = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100)
    with open(path, "w") as f:
        f.writelines(head)
        f.write(body)


def tile_slug(t):
    return t["slug"] if isinstance(t, dict) else t


def tile_state(t):
    return t.get("state", "pinned") if isinstance(t, dict) else "pinned"


def cms_key(live_config):
    """Reuse the viewer api_key already embedded in the live dashboard."""
    env = os.environ.get("CMS_API_KEY")
    if env:
        return env
    src = os.path.expanduser("~/.config/secrets/ada-ha-cms.env")
    if os.path.exists(src):
        m = re.search(r"^CMS_API_KEY=(.+)$", open(src).read(), re.M)
        if m:
            return m.group(1).strip()
    txt = json.dumps(live_config or {})
    m = re.search(r"api_key=([A-Za-z0-9_\-]+)", txt)
    if m:
        return m.group(1)
    raise SystemExit("no CMS api_key found — set CMS_API_KEY or save once")


def cms_pages(spec, key):
    """GET the CMS page index (same endpoint the viewer uses)."""
    # API root = app root without trailing cms/ (same as cmsBasePath() in the viewer)
    base = re.sub(r"cms/?$", "", spec["dashboard"]["cms_base"])
    url = base + "api/cms/pages?limit=500"
    req = urllib.request.Request(url, headers={
        "x-api-key": key, "x-device-id": DEVICE_ID})
    data = json.load(urllib.request.urlopen(req))
    return data["pages"] if isinstance(data, dict) and "pages" in data else data


def topic_rx(t):
    """Discovery regex: explicit match:, else the q= part of reports:."""
    if t.get("match"):
        return t["match"]
    m = re.search(r"[?&]q=([^&\s]+)", "?" + t.get("reports", ""))
    return urllib.parse.unquote(m.group(1)) if m else None


def discover(spec, key):
    """CMS pages matching a topic's regex but absent from its tiles."""
    pages = cms_pages(spec, key)
    out = {}
    for t in spec["topics"]:
        rx, ex = topic_rx(t), t.get("exclude")
        if not rx:
            continue
        have = {tile_slug(x) for x in t["tiles"]}
        cands = [p for p in pages
                 if re.search(rx, f"{p.get('slug','')} {p.get('title','')}", re.I)
                 and (not ex or not re.search(ex, f"{p.get('slug','')} {p.get('title','')}", re.I))
                 and p["slug"] not in have]
        if cands:
            out[t["path"]] = cands
    return out


def build_views(spec, key):
    cms = f"{spec['dashboard']['cms_base']}?api_key={key}"
    zoom, ratio = spec["dashboard"]["zoom"], spec["dashboard"]["tile_aspect"]
    views = [_expand_template(dict(v))
             for v in spec["dashboard"].get("extra_views") or []]
    for t in spec["topics"]:
        name, path = t["name"], t["path"]
        pending = sum(1 for x in t["tiles"] if tile_state(x) != "pinned")
        nudge = f"  ·  **⚠ {pending} proposed — decide**" if pending else ""
        pill = {"type": "markdown", "content":
                f"**{name}**  ·  [All reports →](/{spec['dashboard']['url_path']}/{path}-reports)  ·  "
                "filter: the Reports view has the live filter box" + nudge}
        tiles = []
        for x in t["tiles"]:
            slug, state = tile_slug(x), tile_state(x)
            url = f"{cms}&card=1&zoom={zoom}#/{slug}"
            if state != "pinned":
                why = (x.get("why") if isinstance(x, dict) else None) or \
                    f"{state} tile — added by dashboard auto-discovery"
                url = (f"{cms}&card=1&zoom={zoom}"
                       f"&badge={urllib.parse.quote(state)}"
                       f"&why={urllib.parse.quote(why)}"
                       f"&opts={urllib.parse.quote(BADGE_OPTS.format(slug=slug))}"
                       f"#/{slug}")
            tiles.append({"type": "iframe", "aspect_ratio": ratio, "url": url})
        views.append({"title": name, "path": path, "type": "masonry",
                      "cards": [pill] + tiles})
        views.append({"title": f"{name} — Reports", "path": f"{path}-reports",
                      "subview": True, "back_path": f"/{spec['dashboard']['url_path']}/{path}",
                      "type": "panel",
                      "cards": [{"type": "iframe", "aspect_ratio": "0%",
                                 "url": f"{cms}&{t['reports']}"}]})
    return views


def edit_tile(spec, slug, fn):
    """Apply fn(topic, tile_index) to every occurrence of slug; report count."""
    n = 0
    for t in spec["topics"]:
        for i, x in enumerate(t["tiles"]):
            if tile_slug(x) == slug:
                fn(t, i)
                n += 1
    return n


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ha", default=HA)
    ap.add_argument("--spec", default=SPEC)
    ap.add_argument("--print", dest="p", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--propose", action="store_true")
    ap.add_argument("--auto-add", type=int, metavar="DAYS", default=None,
                    help="auto-add candidates whose page is >=N days old")
    ap.add_argument("--accept", metavar="SLUG")
    ap.add_argument("--reject", metavar="SLUG")
    a = ap.parse_args()
    spec = load_spec(a.spec)

    if a.accept:
        n = edit_tile(spec, a.accept,
                      lambda t, i: t["tiles"].__setitem__(i, tile_slug(t["tiles"][i])))
        if n:
            save_spec(spec, a.spec)
        print(f"pinned {a.accept} in {n} topic(s) — --apply to push")
        return
    if a.reject:
        n = edit_tile(spec, a.reject, lambda t, i: t["tiles"].__setitem__(i, None))
        for t in spec["topics"]:
            t["tiles"] = [x for x in t["tiles"] if x is not None]
        if n:
            save_spec(spec, a.spec)
        print(f"dropped {a.accept or a.reject} from {n} topic(s) — --apply to push")
        return

    token = get_access_token(a.ha)
    ws_url = a.ha.replace("http", "ws", 1) + "/api/websocket"
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
        key = cms_key(live)

        if a.discover:
            cands = discover(spec, key)
            if not cands:
                print("no new candidates — spec covers all matching pages")
                return
            today = datetime.date.today()
            for path, pages in cands.items():
                print(f"\n[{path}] {len(pages)} candidate(s):")
                t = next(x for x in spec["topics"] if x["path"] == path)
                for p in pages:
                    upd = (p.get("updated") or "")[:10]
                    age = (today - datetime.date.fromisoformat(upd)).days \
                        if upd and re.match(r"\d{4}-\d{2}-\d{2}", upd) else None
                    print(f"  {p['slug']:44} {upd}  {p.get('title','')[:60]}")
                    if a.auto_add is not None and age is not None and age >= a.auto_add:
                        t["tiles"].append({"slug": p["slug"], "state": "auto",
                                           "why": f"auto-added: matched {topic_rx(t)!r}, page {age}d old"})
                        print(f"    → auto-added (age {age}d >= {a.auto_add}d)")
                    elif a.propose:
                        t["tiles"].append({"slug": p["slug"], "state": "proposed",
                                           "why": f"proposed: matched {topic_rx(t)!r} on {today}"})
                        print("    → proposed (badge PROPOSED until --accept/--reject)")
            if a.propose or a.auto_add is not None:
                save_spec(spec, a.spec)
                print("\nspec updated — --apply to push")
            else:
                print("\ndry run — --propose to add as PROPOSED, "
                      "--auto-add DAYS to auto-add old candidates")
            return

        views = build_views(spec, key)
        if a.p:
            print(json.dumps({"views": views}, indent=2))
            return
        if a.apply:
            r = await cmd({"type": "lovelace/config/save",
                           "url_path": spec["dashboard"]["url_path"],
                           "config": {"views": views}})
            assert r.get("success"), r
            print(f"saved {spec['dashboard']['url_path']} — {len(views)} views")
            return
        print("dry run — pass --print, --apply, or --discover")


if __name__ == "__main__":
    asyncio.run(main())
