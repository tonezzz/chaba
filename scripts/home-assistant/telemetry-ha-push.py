#!/usr/bin/env python3
"""telemetry-ha-push — mirror device-telemetry battery docs into HA sensors.

Reads `device-telemetry/<dev>/latest` from MDDB (written by the beacon,
scripts/device-telemetry/agent.py) and POSTs sensor/binary_sensor states to
a Home Assistant instance. One shot per run; designed for a systemd timer.

Design notes:
  - HA entities appear on first POST — no HA-side config needed.
  - Stale telemetry (host asleep/off-net) is surfaced as
    binary_sensor.<dev>_telemetry_fresh = off; battery sensors are left at
    their last pushed values instead of being zeroed (quiet failure).
  - capacity may read >100 on Apple hardware (gauge drift); pct is clamped
    for the state value, raw kept as an attribute.

Env:
  TELEMETRY_MDBB     default http://100.102.134.91:11023/v1
  TELEMETRY_DEVICES  default "macbook" — comma list of beacon device names
  HA_URL             default https://tony-omen.taila0626a.ts.net:8123
  HA_TOKEN_FILE      default ~/.config/secrets/home-assistant-token.env
                     (line `HA_LONG_LIVED_TOKEN=` or `HASS_TOKEN=`)
  STALE_SECONDS      default 900 — doc ts older than this => fresh=off
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

MDDB = os.environ.get("TELEMETRY_MDBB",
                      "http://100.102.134.91:11023/v1").rstrip("/")
DEVICES = [d.strip() for d in os.environ.get(
    "TELEMETRY_DEVICES", "macbook").split(",") if d.strip()]
HA_URL = os.environ.get(
    "HA_URL", "https://tony-omen.taila0626a.ts.net:8123").rstrip("/")
STALE_S = int(os.environ.get("STALE_SECONDS", "900"))
COLLECTION = "device-telemetry"


def _token() -> str:
    env = Path(os.environ.get(
        "HA_TOKEN_FILE",
        str(Path.home() / ".config/secrets/home-assistant-token.env")))
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith(("HA_LONG_LIVED_TOKEN=", "HASS_TOKEN=")):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _post(url: str, body: dict, token: str = "", timeout: int = 20):
    headers = {"content-type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _latest(dev: str) -> dict | None:
    doc = _post(f"{MDDB}/get",
                {"collection": COLLECTION, "key": f"{dev}/latest",
                 "lang": "en"}, timeout=10)
    if not doc:
        return None
    return json.loads(doc.get("contentMd") or "{}")


def _push(token: str, entity: str, state, attrs: dict) -> None:
    _post(f"{HA_URL}/api/states/{entity}",
          {"state": state, "attributes": attrs}, token=token)


def push_device(dev: str, token: str) -> str:
    eid = dev.replace("-", "_")  # entity_ids may not contain hyphens
    doc = _latest(dev)
    now = int(time.time())
    if not doc or not doc.get("ts"):
        return f"{dev}: no telemetry doc"
    age = now - int(doc["ts"])
    fresh = "on" if age <= STALE_S else "off"
    _push(token, f"binary_sensor.{eid}_telemetry_fresh", fresh, {
        "friendly_name": f"{dev} telemetry fresh",
        "device_class": "connectivity",
        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                   time.localtime(int(doc["ts"]))),
        "age_seconds": age,
    })
    b = doc.get("battery") or {}
    if not b:
        return f"{dev}: fresh={fresh} age={age}s (no battery)"
    common = {
        "status": b.get("status"),
        "model_name": b.get("model_name"),
        "manufacturer": b.get("manufacturer"),
        "technology": b.get("technology"),
        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                   time.localtime(int(doc["ts"]))),
        "telemetry_age_s": age,
    }
    pct = b.get("pct")
    if pct is not None:
        _push(token, f"sensor.{dev}_battery", min(int(pct), 100), {
            "friendly_name": f"{dev} battery",
            "device_class": "battery",
            "unit_of_measurement": "%",
            "state_class": "measurement",
            "raw_pct": int(pct),
            **common,
        })
        # household convention pair — matches tony_omen / kk_macbook
        # battery_level/battery_state entities + battery_reminder_* automations
        _push(token, f"sensor.{eid}_battery_level", min(int(pct), 100), {
            "friendly_name": f"{dev} battery level",
            "device_class": "battery",
            "unit_of_measurement": "%",
            "state_class": "measurement",
            **common,
        })
        _push(token, f"sensor.{eid}_battery_state",
              b.get("status") or "unknown", {
                  "friendly_name": f"{dev} battery state",
                  "icon": "mdi:battery",
                  **common,
              })
    if b.get("health_pct") is not None:
        _push(token, f"sensor.{dev}_battery_health",
              min(round(float(b["health_pct"]), 1), 100.0), {
                  "friendly_name": f"{dev} battery health",
                  "unit_of_measurement": "%",
                  "state_class": "measurement",
                  "icon": "mdi:battery-heart",
                  "raw_health_pct": b["health_pct"],
                  "charge_full_uah": b.get("charge_full_uah"),
                  "charge_full_design_uah": b.get("charge_full_design_uah"),
                  **common,
              })
    if b.get("cycle_count") is not None:
        _push(token, f"sensor.{dev}_battery_cycles", int(b["cycle_count"]), {
            "friendly_name": f"{dev} battery cycles",
            "state_class": "total_increasing",
            "icon": "mdi:battery-sync",
            **common,
        })
    if b.get("temp_dxc") is not None:
        _push(token, f"sensor.{dev}_battery_temp",
              round(int(b["temp_dxc"]) / 10.0, 1), {
                  "friendly_name": f"{dev} battery temp",
                  "device_class": "temperature",
                  "unit_of_measurement": "°C",
                  "state_class": "measurement",
                  **common,
              })
    if b.get("voltage_now_uv") is not None:
        _push(token, f"sensor.{dev}_battery_voltage",
              round(int(b["voltage_now_uv"]) / 1e6, 3), {
                  "friendly_name": f"{dev} battery voltage",
                  "device_class": "voltage",
                  "unit_of_measurement": "V",
                  "state_class": "measurement",
                  "current_now_ua": b.get("current_now_ua"),
                  **common,
              })
    return (f"{dev}: pct={pct} health={b.get('health_pct')} "
            f"cycles={b.get('cycle_count')} fresh={fresh} age={age}s")


def main() -> int:
    token = _token()
    if not token:
        print("telemetry-ha-push: no HA token (HA_TOKEN_FILE)",
              file=sys.stderr)
        return 1
    rc = 0
    for dev in DEVICES:
        try:
            print(push_device(dev, token))
        except Exception as exc:  # quiet: asleep/off-net devices are normal
            print(f"{dev}: push failed: {exc}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
