#!/usr/bin/env python3
"""Dev/live entity parity lint + mirror generator for michael-dev.

Compares entity ids referenced by the tony-test dashboard on michael-dev
against dev's actual states. Missing entities that exist on michael-ha can
be emitted as ready-to-paste `rest:` mirror blocks for
docs/home-assistant/dev/dev-mocks.yaml (deployed as packages/a_dev_mocks.yaml).

Usage:
    mirror-sweep.py                     # report only (parity lint)
    mirror-sweep.py --yaml              # also emit rest mirror YAML to stdout
    mirror-sweep.py --ha-only           # skip dev states; list entities missing vs ha

Env:
    DEV_TOKEN / HASS_TOKEN   token for michael-dev (default: reads
                             ~/.config/secrets/ha-michael-dev.env)
    HA_TOKEN                 token for michael-ha (default: reads
                             ~/.local/share/home-assistant-michael/ha-token)
    DEV_URL, HA_URL          override base urls
"""
import json
import os
import re
import sys
import urllib.request
import asyncio
import websockets

DEV_URL = os.environ.get(
    "DEV_URL", "https://tony-dell.taila0626a.ts.net:8124"
)
HA_URL = os.environ.get("HA_URL", "http://michael-ha:8123")
DASH = os.environ.get("DASH", "tony-test")

ENTITY_RE = re.compile(
    r"^(?:sensor|binary_sensor|input_number|input_select|input_boolean|"
    r"input_datetime|number|select|switch|light|fan|climate|media_player|"
    r"cover|lock|button|weather|update|device_tracker|person|zone|"
    r"automation|script|scene|counter|timer|sun)\.[a-z0-9_]+$"
)


def load_token(path, env_names):
    for name in env_names:
        if os.environ.get(name):
            return os.environ[name]
    try:
        for line in open(os.path.expanduser(path)):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                if k in ("HASS_TOKEN", "DEV_TOKEN", "HA_TOKEN"):
                    return v.strip().strip('"').strip("'")
            elif line.strip():
                return line.strip()  # raw token file
    except OSError:
        pass
    return None


def get_json(url, token):
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}
    )
    ctx = None
    if url.startswith("https"):
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return json.load(urllib.request.urlopen(req, context=ctx, timeout=15))


async def get_dashboard(url, token):
    ws_url = url.replace("http", "ws", 1) + "/api/websocket"
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
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        await ws.recv()
        cfg = await cmd({"type": "lovelace/config", "url_path": DASH})
        return cfg["result"]


def collect_entities(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and ENTITY_RE.match(v):
                out.add(v)
            elif isinstance(v, (dict, list)):
                collect_entities(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_entities(v, out)


def main():
    want_yaml = "--yaml" in sys.argv
    ha_only = "--ha-only" in sys.argv

    dev_token = load_token(
        "~/.config/secrets/ha-michael-dev.env", ["DEV_TOKEN", "HASS_TOKEN"]
    )
    ha_token = load_token(
        "~/.local/share/home-assistant-michael/ha-token", ["HA_TOKEN"]
    )
    if not dev_token:
        sys.exit("no dev token (set DEV_TOKEN or HASS_TOKEN)")
    if not ha_token:
        sys.exit("no ha token (set HA_TOKEN or token file)")

    cfg = asyncio.run(get_dashboard(DEV_URL, dev_token))
    entities = set()
    collect_entities(cfg, entities)

    ha_states = {
        s["entity_id"]: s
        for s in get_json(f"{HA_URL}/api/states", ha_token)
    }
    missing_ha = sorted(e for e in entities if e not in ha_states)

    if ha_only:
        dev_states = {}
        missing_dev = []
    else:
        dev_states = {
            s["entity_id"]: s
            for s in get_json(f"{DEV_URL}/api/states", dev_token)
        }
        missing_dev = sorted(e for e in entities if e not in dev_states)

    print(f"dashboard entities referenced: {len(entities)}")
    print(f"missing on michael-ha: {len(missing_ha)}")
    for e in missing_ha:
        print(f"  [ha-missing] {e}")
    if not ha_only:
        print(f"missing on michael-dev: {len(missing_dev)}")
        for e in missing_dev:
            tag = "mirrorable" if e in ha_states else "no-ha-source"
            print(f"  [dev-missing:{tag}] {e}")

    if want_yaml:
        mirrorable = [e for e in (missing_dev if not ha_only else missing_ha) if e in ha_states]
        if not mirrorable:
            print("# nothing to mirror")
            return
        print("\n# --- append to docs/home-assistant/dev/dev-mocks.yaml under rest: ---")
        for e in mirrorable:
            attrs = ha_states[e].get("attributes", {})
            unit = attrs.get("unit_of_measurement")
            dc = attrs.get("device_class")
            slug = re.sub(r"[^a-z0-9]+", "_", e.split(".", 1)[1])
            print(f"  - resource: {HA_URL}/api/states/{e}")
            print("    headers:")
            print("      Authorization: !secret michael_ha_auth")
            print("    scan_interval: 30")
            print("    sensor:")
            print(f"      - name: {e.split('.', 1)[1]}")
            print(f"        unique_id: mha_mirror_{slug}")
            print('        value_template: "{{ value_json.state }}"')
            if unit:
                print(f'        unit_of_measurement: "{unit}"')
            SENSOR_CLASSES = {
                'apparent_power','battery','carbon_dioxide','carbon_monoxide',
                'current','data_rate','data_size','distance','duration',
                'energy','energy_storage','frequency','gas','humidity',
                'illuminance','irradiance','moisture','monetary',
                'nitrogen_dioxide','nitrogen_monoxide','nitrous_oxide',
                'ozone','ph','pm1','pm10','pm25','pm4','power',
                'power_factor','precipitation','precipitation_intensity',
                'pressure','reactive_power','signal_strength',
                'sound_pressure','speed','temperature','voltage',
                'volatile_organic_compounds','volume','water','weight',
                'wind_speed','wind_direction',
            }
            if dc and dc in SENSOR_CLASSES:
                print(f"        device_class: {dc}")
            try:
                float(ha_states[e]["state"])
                sc = 'total' if dc == 'energy' else 'measurement'
                print(f"        state_class: {sc}")
            except (ValueError, TypeError):
                pass
            print()


if __name__ == "__main__":
    main()
