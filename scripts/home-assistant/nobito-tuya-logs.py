#!/usr/bin/env python3
"""Fetch Nobito datapoint logs from Tuya Cloud and optionally backfill
them into Home Assistant long-term statistics.

Why: Nobito is a battery Tuya air sensor on tony-ha. The official Tuya
integration only refreshes entities at config-entry setup (MQ push is dead
for this account — see tuya_entry_reload_watchdog), so HA recorder sees only
hourly snapshots and the chaba-home/Nobito 3D range chart looks flat. Tuya
cloud keeps richer per-DP report logs; this tool pulls them via the developer
OpenAPI project and can import hourly aggregates via recorder/import_statistics
so the existing `stat: "range"` bar3d tiles show real lo-hi variation.

Requires: the IoT Core service subscription on the Tuya developer project
(~/.local/share/tuya/project-creds.json) — it lapses monthly; renew at
iot.tuya.com -> Cloud -> Cloud Services. All calls return code 28841002
while expired (probe checks this).

Usage:
  nobito-tuya-logs.py probe                      # check creds + subscription
  nobito-tuya-logs.py list                       # list project devices
  nobito-tuya-logs.py fetch [--days 7] [--codes a,b] [--out DIR]
  nobito-tuya-logs.py import [--dir DIR] [--dry-run] [--ha-url URL]
  nobito-tuya-logs.py live    # current values via HA's own Tuya token — NO
                            # developer subscription needed (consumer API)

Runs under system python3; tinytuya is loaded from the local venv at
~/.local/share/tuya/venv (sys.path shim — no install needed).

HA token: HASS_TOKEN / HOME_ASSISTANT_TOKEN env, else
~/.config/secrets/home-assistant-token.env (HA_LONG_LIVED_TOKEN).
"""
import argparse, glob, json, os, sys, time
from collections import defaultdict
from datetime import datetime, timezone

TUYA_DIR = os.path.expanduser("~/.local/share/tuya")
CREDS = os.path.join(TUYA_DIR, "project-creds.json")
OUT_DIR = os.path.join(TUYA_DIR, "nobito-logs")
REGION = "sg"
DEVICE_ID = "a35dc1b618d6a2378a3tzw"  # tony-ha device registry identifier
LOG_TYPE = "7"                       # 7 = DP report events
EXPIRED = "28841002"                 # IoT Core subscription expired

# DP code -> HA entity_id + unit, recovered from entity-registry unique_ids
# (tuya.<device_id><dp_code>). Verified 2026-09-26, no cloud call needed.
DPS = {
    "pm25_value": ("sensor.nobito_pm2_5", "µg/m³"),
    "pm10": ("sensor.nobito_pm10", "µg/m³"),
    "co2_value": ("sensor.nobito_carbon_dioxide", "ppm"),
    "temp_current": ("sensor.nobito_temperature", "°C"),
    "humidity_value": ("sensor.nobito_humidity", "%"),
    "voc_value": ("sensor.nobito_volatile_organic_compounds", "mg/m³"),
    "ch2o_value": ("sensor.nobito_formaldehyde", "mg/m³"),
    "air_quality_index": ("sensor.nobito_air_quality_index", ""),
    "battery_percentage": ("sensor.nobito_battery", "%"),
    # battery_state (enum low/middle/high), charge_state (bool) — not importable
}
# Fetched for completeness but no HA entity exists: pm1, co_value,
# charge_state, battery_state.
EXTRA_DPS = ["pm1", "co_value", "charge_state", "battery_state"]

# Raw DP value -> HA unit multipliers, verified against the live
# /v1.1/m/life/{id}/specifications (category hjjcy) on 2026-09-26:
# temp_current scale=1, ch2o_value/voc_value scale=3, the rest scale=0.
SCALE = {"temp_current": 0.1, "ch2o_value": 0.001, "voc_value": 0.001}

NUMERIC_DPS = [c for c, (e, u) in DPS.items() if u]

for sp in glob.glob(os.path.join(TUYA_DIR, "venv/lib/python*/site-packages")):
    if sp not in sys.path:
        sys.path.insert(0, sp)


def cloud():
    import tinytuya
    creds = json.load(open(CREDS))
    c = tinytuya.Cloud(apiRegion=REGION, apiKey=creds["apiKey"],
                       apiSecret=creds["apiSecret"],
                       apiDeviceID=creds.get("project_code"))
    return c


def is_expired(resp):
    return EXPIRED in json.dumps(resp)


def check(resp):
    """Normalize cloud responses; raise SystemExit with a clear message."""
    if resp is None:
        raise SystemExit("no response from Tuya cloud")
    if is_expired(resp):
        raise SystemExit(
            "IoT Core subscription expired (code 28841002). Renew the trial "
            "at iot.tuya.com -> project -> Cloud -> Cloud Services, wait ~2-3 "
            "min, then re-run `probe`.")
    return resp


def cmd_probe(args):
    c = cloud()
    r = c.cloudrequest(f"/v1.0/devices/{args.device_id}")
    if is_expired(r):
        print("EXPIRED: IoT Core subscription expired (28841002) — "
              "renew trial at iot.tuya.com -> Cloud -> Cloud Services")
        return 2
    if not isinstance(r, dict) or r.get("success") is False:
        print("ERROR:", json.dumps(r)[:400])
        return 3
    res = r.get("result", r)
    print(f"OK: subscription active; device '{res.get('name', '?')}' "
          f"online={res.get('online')}")
    return 0


def cmd_list(args):
    c = cloud()
    devs = check(c.getdevices(verbose=False))
    if not isinstance(devs, list):
        print("ERROR:", json.dumps(devs)[:400])
        return 3
    for d in devs:
        print(f"{d.get('id')} | {d.get('name')} | {d.get('category')} | "
              f"online={d.get('online')}")
    return 0


def cmd_fetch(args):
    c = cloud()
    codes = args.codes.split(",") if args.codes else list(DPS) + EXTRA_DPS
    outdir = args.dir
    os.makedirs(outdir, exist_ok=True)
    now = int(time.time() * 1000)
    start = now - args.days * 86_400_000
    total = 0
    for code in codes:
        rows, last_key, pages = [], None, 0
        while True:
            q = {"type": LOG_TYPE, "codes": code, "start_time": start,
                 "end_time": now, "size": 100, "query_type": 1}
            if last_key:
                q["last_row_key"] = last_key
            r = check(c.cloudrequest(
                f"/v1.0/devices/{args.device_id}/logs", query=q))
            res = r.get("result") or {}
            if not res and not rows:
                print(f"{code}: unexpected response "
                      f"{json.dumps(r)[:300]}")
                break
            rows.extend(res.get("logs") or [])
            pages += 1
            nk = res.get("next_row_key") or res.get("last_row_key")
            if not res.get("has_more") or not nk or pages >= args.max_pages:
                break
            last_key = nk
        path = os.path.join(outdir, f"{code}.jsonl")
        mode = "a" if args.append and os.path.exists(path) else "w"
        with open(path, mode) as f:
            for row in rows:
                f.write(json.dumps({"code": code, "ts": row.get("event_time"),
                                    "value": row.get("value")}) + "\n")
        total += len(rows)
        print(f"{code}: {len(rows)} log rows ({pages} page(s)) -> {path}")
    print(f"done: {total} rows in {outdir}")
    return 0


# --- live status via the HA tuya_sharing consumer token ---------------------
# The Smart-Life user path (apigw-sg.iotbing.com) is independent of the
# expired developer subscription. tuya_sharing lives inside the tony-ha
# container, so we exec in and read the token straight from the config
# entry. SAFETY: we bail if the access token is expired/near-expiry —
# a refresh here would rotate the refresh_token and orphan HA's stored copy
# (HA's runtime listener writes rotations back via update_token; we can't).
_LIVE_PY = """
import json, sys
from tuya_sharing.customerapi import (CustomerApi, CustomerTokenInfo,
                                      SharingTokenListener)
d = json.load(open('/config/.storage/core.config_entries'))
data = [e for e in d['data']['entries'] if e['domain'] == 'tuya'][0]['data']
ti_raw = data['token_info']
import time
if ti_raw.get('t', 0) + ti_raw.get('expire_time', 0) * 1000 \\
        < int(time.time() * 1000) + 60_000:
    sys.exit('token near expiry — reload the tuya config entry first '
             '(automation tuya_entry_reload_watchdog does it hourly)')
class L(SharingTokenListener):
    def update_token(self, t): print('WARN token rotated')
api = CustomerApi(CustomerTokenInfo(ti_raw), 'HA_3y9q4ak7g4ephrvke',
                  data['user_code'], data['endpoint'], L())
det = api.get('/v1.0/m/life/ha/devices/detail', {'devIds': '%s'})
dev = det['result'][0]
print(json.dumps({'name': dev.get('name'), 'online': dev.get('online'),
                  'status': {i['code']: i['value']
                             for i in dev.get('status', [])}}))
"""


def cmd_live(args):
    import subprocess
    r = subprocess.run(
        ["podman", "exec", "-i", "tony-ha", "python3", "-"],
        input=_LIVE_PY % args.device_id, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr.strip() or "podman exec failed")
        return 3
    out = r.stdout.strip()
    if out.startswith("token near expiry"):
        print(out)
        return 3
    print(out)
    try:
        st = json.loads(out.splitlines()[-1])
        applied = {k: round(v * SCALE[k], 4) if isinstance(v, (int, float))
                   and k in SCALE else v for k, v in st["status"].items()}
        print("scaled (HA units):", json.dumps(applied))
    except (ValueError, KeyError):
        pass
    return 0


def ha_token():
    for k in ("HASS_TOKEN", "HOME_ASSISTANT_TOKEN", "HA_LONG_LIVED_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    for path, key in ((os.path.expanduser(
            "~/.config/secrets/home-assistant-token.env"),
            "HA_LONG_LIVED_TOKEN"),):
        if os.path.exists(path):
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no HA token: set HASS_TOKEN or populate "
                     "~/.config/secrets/home-assistant-token.env")


def cmd_import(args):
    import asyncio
    import websockets

    # aggregate JSONL -> hourly stats per DP
    buckets = defaultdict(lambda: defaultdict(list))  # code -> hour -> [v]
    d = args.dir
    files = sorted(glob.glob(os.path.join(d, "*.jsonl")))
    if not files:
        raise SystemExit(f"no *.jsonl in {d} — run `fetch` first")
    scale = dict(SCALE)
    scale.update({k: float(v) for k, v in
                  (s.split("=", 1) for s in args.scale or [])})
    for path in files:
        for line in open(path):
            try:
                rec = json.loads(line)
                v = float(rec["value"]) * scale.get(rec["code"], 1)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue  # non-numeric DP (e.g. battery_state enum)
            hour = datetime.fromtimestamp(
                rec["ts"] / 1000, tz=timezone.utc).astimezone().replace(
                minute=0, second=0, microsecond=0)
            buckets[rec["code"]][hour].append(v)

    jobs = {}
    for code, by_hour in buckets.items():
        entity, unit = DPS.get(code, (None, None))
        if not entity or code not in NUMERIC_DPS:
            continue
        stats = [{"start": h.isoformat(),
                  "min": min(vs), "max": max(vs),
                  "mean": round(sum(vs) / len(vs), 4)}
                 for h, vs in sorted(by_hour.items())]
        jobs[entity] = {"unit": unit, "stats": stats}
    if not jobs:
        raise SystemExit("nothing to import")

    async def push():
        url = args.ha_url.replace("http", "ws", 1) + "/api/websocket"
        async with websockets.connect(url) as ws:
            await ws.recv()  # auth_required
            await ws.send(json.dumps({"type": "auth",
                                      "access_token": ha_token()}))
            r = json.loads(await ws.recv())
            if r.get("type") != "auth_ok":
                raise SystemExit(f"HA auth failed: {r}")
            mid = 0

            async def call(payload):
                nonlocal mid
                mid += 1
                await ws.send(json.dumps({"id": mid, **payload}))
                return json.loads(await ws.recv())

            # reuse existing entity statistic metadata where present
            r = await call({"type": "recorder/list_statistic_ids",
                            "statistic_type": "mean"})
            known = {s["statistic_id"]: s for s in r.get("result", [])}
            for entity, job in jobs.items():
                meta = known.get(entity, {})
                unit = meta.get("unit_of_measurement") or job["unit"]
                print(f"{entity}: {len(job['stats'])} hourly rows "
                      f"(unit={unit})")
                if args.dry_run:
                    print("  sample:", json.dumps(job["stats"][:2]))
                    continue
                r = await call({
                    "type": "recorder/import_statistics",
                    "metadata": {"has_mean": True, "has_sum": False,
                                 "name": None, "source": "recorder",
                                 "statistic_id": entity,
                                 "unit_of_measurement": unit},
                    "stats": job["stats"]})
                if not r.get("success"):
                    print(f"  ERROR {entity}: {r.get('error')}")

    asyncio.run(push())
    print("dry-run: nothing written" if args.dry_run else "import complete")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="\n".join(__doc__.splitlines()[2:]))
    ap.add_argument("command", choices=["probe", "list", "fetch", "import",
                                        "live"])
    ap.add_argument("--device-id", default=DEVICE_ID)
    ap.add_argument("--days", type=int, default=7,
                    help="log window; free tier (query_type=1) caps at 7d")
    ap.add_argument("--codes", help="comma-separated DP codes "
                    f"(default: all known: {','.join(list(DPS) + EXTRA_DPS)})")
    ap.add_argument("--out", "--dir", dest="dir", default=OUT_DIR,
                    help=f"JSONL dir (default {OUT_DIR})")
    ap.add_argument("--max-pages", type=int, default=50)
    ap.add_argument("--append", action="store_true",
                    help="append to existing JSONL instead of overwriting")
    ap.add_argument("--scale", nargs="*", metavar="CODE=FACTOR",
                    help="override the built-in raw->HA-unit multipliers "
                    "(verified defaults: temp_current=0.1, "
                    "ch2o_value=0.001, voc_value=0.001)")
    ap.add_argument("--ha-url", default="http://127.0.0.1:8123",
                    help="tony-ha binds loopback only")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return {"probe": cmd_probe, "list": cmd_list, "live": cmd_live,
            "fetch": cmd_fetch, "import": cmd_import}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
