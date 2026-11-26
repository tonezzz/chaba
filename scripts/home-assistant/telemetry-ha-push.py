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
  TELEMETRY_TEMP_ALERT_C  default 80 — binary_sensor.<dev>_temp_high threshold
                     (uses the hottest of all reported zones, not just CPU)
  TELEMETRY_TEMP_SKIP_DEVICES  default kk-mac — hosts with their own stricter
                     admission gate are not duplicated here.
  CHABA_THERMAL_CONFIG      Ansible-managed ~/.config/chaba/thermal.env;
                     its values are used unless the env vars above are set.
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


def _thermal_config() -> dict:
    """Read the Ansible-managed threshold file (KEY=VALUE, # comments)."""
    path = Path(os.environ.get(
        "CHABA_THERMAL_CONFIG",
        str(Path.home() / ".config/chaba/thermal.env")))
    out = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    except OSError:
        pass
    return out


TEMP_CFG = _thermal_config()


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
    try:
        doc = _post(f"{MDDB}/get",
                    {"collection": COLLECTION, "key": f"{dev}/latest",
                     "lang": "en"}, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None
        raise
    if not doc:
        return None
    return json.loads(doc.get("contentMd") or "{}")


def _push(token: str, entity: str, state, attrs: dict) -> None:
    _post(f"{HA_URL}/api/states/{entity}",
          {"state": state, "attributes": attrs}, token=token)


def common_attrs(doc: dict, age: int) -> dict:
    return {
        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                   time.localtime(int(doc["ts"]))),
        "telemetry_age_s": age,
        "os": doc.get("os"),
        "wan_city": (doc.get("wan") or {}).get("city"),
        "wan_country": (doc.get("wan") or {}).get("country"),
    }


def push_device(dev: str, token: str) -> str:
    eid = dev.replace("-", "_")  # entity_ids may not contain hyphens
    doc = _latest(dev)
    now = int(time.time())
    if not doc or not doc.get("ts"):
        # No telemetry doc (host never reported, or MDDB miss): surface the
        # host as offline/stale instead of leaving the last pushed online
        # state (which can stay "on" for a sleeping laptop like kk-mac).
        # Battery/metric sensors are left untouched (quiet failure).
        try:
            _push(token, f"binary_sensor.{eid}_online", "off", {
                "friendly_name": f"{dev} online",
                "device_class": "connectivity",
            })
            _push(token, f"binary_sensor.{eid}_telemetry_fresh", "off", {
                "friendly_name": f"{dev} telemetry fresh",
                "device_class": "connectivity",
                "age_seconds": None,
            })
        except Exception:
            pass
        return f"{dev}: no telemetry doc"
    age = now - int(doc["ts"])
    fresh = "on" if age <= STALE_S else "off"
    # Stale telemetry means the host has not reported recently (e.g. asleep /
    # off-net), so it must not be shown as online even if the last doc's
    # tailnet.online was true.
    online = "on" if ((doc.get("tailnet") or {}).get("online")
                      and age <= STALE_S) else "off"
    _push(token, f"binary_sensor.{eid}_online", online, {
        "friendly_name": f"{dev} online",
        "device_class": "connectivity",
        **common_attrs(doc, age),
    })
    up = doc.get("uptime_s")
    if up is not None:
        _push(token, f"sensor.{eid}_uptime", round(int(up) / 3600.0, 1), {
            "friendly_name": f"{dev} uptime",
            "unit_of_measurement": "h",
            "state_class": "measurement",
            "icon": "mdi:clock-outline",
            **common_attrs(doc, age),
        })
    def _metric(key, suffix, label, unit, icon, extra=None):
        v = doc.get(key)
        if v is None:
            return
        attrs = {"friendly_name": f"{dev} {label}",
                 "unit_of_measurement": unit,
                 "state_class": "measurement",
                 "icon": icon,
                 **common_attrs(doc, age)}
        if extra:
            attrs.update(extra)
        _push(token, f"sensor.{eid}_{suffix}", v, attrs)
    _metric("load1", "load", "load", None, "mdi:server")
    _metric("mem_pct", "mem", "memory", "%", "mdi:memory")
    _metric("disk_pct", "disk", "disk", "%", "mdi:harddisk")
    _metric("swap_pct", "swap", "swap", "%", "mdi:swap-horizontal")
    _metric("temp_c", "temp", "temp", "°C", "mdi:thermometer",
            {"temps": doc.get("temp_zones") or {}})
    zones = doc.get("temp_zones") or {}
    if zones:
        def _zname(k: str) -> str:
            if k == "x86_pkg_temp":
                return "pkg"
            if k.startswith("pch_"):
                return "pch"
            return k
        top = sorted(zones.items(), key=lambda kv: -kv[1])[:1]
        pairs = ",".join(f"{_zname(k)}:{v:g}°" for k, v in top)
        _push(token, f"sensor.{eid}_temps", pairs[:200], {
            "friendly_name": f"{dev} temps",
            "icon": "mdi:thermometer-lines",
            **common_attrs(doc, age),
        })
    elif doc.get("temp_c") is None:
        # host reports no thermal zones — clear any stale temps state
        # (e.g. leftover from a previous agent/doc) instead of leaving it
        _push(token, f"sensor.{eid}_temps", "unknown", {
            "friendly_name": f"{dev} temps",
            "icon": "mdi:thermometer-lines",
            **common_attrs(doc, age),
        })
    # Safety view: one boolean per host driven by the hottest zone, not just
    # the CPU package. Unknown temp (sensorless VM, failed probe) clears the
    # alert rather than raising a false one; freshness is reported separately.
    temp_limit = float(TEMP_CFG.get(
        "TELEMETRY_TEMP_ALERT_C",
        os.environ.get("TELEMETRY_TEMP_ALERT_C", "80")))
    skip = {d.strip() for d in TEMP_CFG.get(
        "TELEMETRY_TEMP_SKIP_DEVICES",
        os.environ.get("TELEMETRY_TEMP_SKIP_DEVICES", "kk-mac")
    ).split(",") if d.strip()}
    excluded = dev in skip
    temp_c = doc.get("temp_c")
    hot = (not excluded and temp_c is not None
           and float(temp_c) > temp_limit)
    _push(token, f"binary_sensor.{eid}_temp_high",
          "on" if hot else "off", {
              "friendly_name": f"{dev} temp above {temp_limit:g}C",
              "device_class": "problem",
              "icon": "mdi:thermometer-alert",
              "max_temp_c": temp_c,
              "limit_c": temp_limit,
              "excluded": excluded,
              **common_attrs(doc, age),
          })
    tp = doc.get("thermal_pressure")
    if tp:
        _push(token, f"sensor.{eid}_thermal", str(tp), {
            "friendly_name": f"{dev} thermal",
            "icon": "mdi:thermometer-alert",
            **common_attrs(doc, age),
        })
    for sname, sinfo in (doc.get("services") or {}).items():
        sid = "".join(c if c.isalnum() else "_"
                      for c in sname.lower()).strip("_")
        _push(token, f"binary_sensor.{eid}_svc_{sid}",
              "on" if sinfo.get("state") == "running" else "off", {
                  "friendly_name": f"{dev} {sname}",
                  "device_class": "running",
                  **common_attrs(doc, age),
              })
        for mk, mv in sinfo.items():
            if mk in ("state", "age_s") or mv is None:
                continue
            msuf = "".join(c if c.isalnum() else "_"
                           for c in mk.lower()).strip("_")
            attrs = {"friendly_name": f"{dev} {sname} {mk}",
                     "icon": "mdi:information-outline",
                     **common_attrs(doc, age)}
            if isinstance(mv, (int, float)):
                attrs["state_class"] = "measurement"
            _push(token, f"sensor.{eid}_svc_{sid}_{msuf}", mv, attrs)
    for key, suffix, label, icon in (
            ("net_rx_b", "net_rx", "net rx", "mdi:download-network"),
            ("net_tx_b", "net_tx", "net tx", "mdi:upload-network")):
        v = doc.get(key)
        if v is not None:
            _push(token, f"sensor.{eid}_{suffix}", round(v / 1e9, 2), {
                "friendly_name": f"{dev} {label}",
                "unit_of_measurement": "GB",
                "state_class": "total_increasing",
                "icon": icon,
                **common_attrs(doc, age),
            })
    tp = (doc.get("top_procs") or [None])[0]
    if tp:
        _push(token, f"sensor.{eid}_top_proc", str(tp)[:80], {
            "friendly_name": f"{dev} top proc",
            "icon": "mdi:application-cog",
            **common_attrs(doc, age),
        })
    wan = doc.get("wan") or {}
    for key, suffix, label in (("city", "wan_city", "wan city"),
                               ("country", "wan_country", "wan country"),
                               ("org", "wan_org", "wan isp")):
        v = wan.get(key)
        if v:
            _push(token, f"sensor.{eid}_{suffix}", str(v)[:80], {
                "friendly_name": f"{dev} {label}",
                "icon": "mdi:earth",
                **common_attrs(doc, age),
            })
    users = doc.get("users") or []
    _push(token, f"sensor.{eid}_users", len(users), {
        "friendly_name": f"{dev} users",
        "state_class": "measurement",
        "icon": "mdi:account-group",
        "users": ",".join(users),
        **common_attrs(doc, age),
    })
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
        _push(token, f"sensor.{eid}_battery", min(int(pct), 100), {
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
        _push(token, f"sensor.{eid}_battery_health",
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
        _push(token, f"sensor.{eid}_battery_cycles", int(b["cycle_count"]), {
            "friendly_name": f"{dev} battery cycles",
            "state_class": "total_increasing",
            "icon": "mdi:battery-sync",
            **common,
        })
    if b.get("temp_dxc") is not None:
        _push(token, f"sensor.{eid}_battery_temp",
              round(int(b["temp_dxc"]) / 10.0, 1), {
                  "friendly_name": f"{dev} battery temp",
                  "device_class": "temperature",
                  "unit_of_measurement": "°C",
                  "state_class": "measurement",
                  **common,
              })
    if b.get("voltage_now_uv") is not None:
        _push(token, f"sensor.{eid}_battery_voltage",
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
