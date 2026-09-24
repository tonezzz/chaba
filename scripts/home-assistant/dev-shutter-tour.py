#!/usr/bin/env python3
"""Guided tour for the mn-weather Shutter Logic Test card on michael-dev.

Drives input_number sliders + toggles through a narrated close/open scenario
while the user watches the card. Reads HASS_TOKEN and HA_URL from env
(default http://127.0.0.1:8124; source ~/.config/secrets/ha-michael-dev.env).

Usage:
    python3 dev-shutter-tour.py            # narrated tour, pauses between steps
    python3 dev-shutter-tour.py --pause 3  # faster pacing
    python3 dev-shutter-tour.py --status   # just print the tour-request flag
"""
import argparse
import json
import os
import sys
import time
import urllib.request

HA = os.environ.get("HA_URL", "http://127.0.0.1:8124").rstrip("/")
TOKEN = os.environ.get("HASS_TOKEN") or os.environ.get("HA_LONG_LIVED_TOKEN")
if not TOKEN:
    sys.exit("HASS_TOKEN not set — source ~/.config/secrets/ha-michael-dev.env")

HDRS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

ENT = {
    "sim": "input_boolean.dev_simulation",
    "flag": "input_boolean.dev_tour_request",
    "state": "input_boolean.dev_shutter_state",
    "status": "sensor.dev_shutter_status",
    "dir": "input_number.dev_wind_direction",
    "spd": "input_number.dev_wind_speed",
    "rain": "input_number.dev_rainfall",
    "dmin": "input_number.shutter_wind_dir_min",
    "dmax": "input_number.shutter_wind_dir_max",
    "smin": "input_number.shutter_wind_speed_min",
    "rmin": "input_number.shutter_rain_min",
    "eff_dir": "sensor.dev_wind_direction",
    "eff_spd": "sensor.dev_wind_speed",
    "eff_rain": "sensor.dev_rainfall",
}


def api(path, data=None):
    req = urllib.request.Request(
        f"{HA}/api/{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers=HDRS,
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"[]")


def state(eid):
    try:
        return api(f"states/{eid}")["state"]
    except Exception:
        return "unknown"


def num(eid):
    try:
        return float(state(eid))
    except ValueError:
        return 0.0


def call(domain, service, **data):
    api(f"services/{domain}/{service}", data)


def set_num(eid, value):
    call("input_number", "set_value", entity_id=eid, value=value)


def set_bool(eid, on):
    call("input_boolean", "turn_on" if on else "turn_off", entity_id=eid)


def wait_status(expect, timeout=8):
    """Poll dev_shutter_status until it matches; return final value."""
    deadline = time.time() + timeout
    s = state(ENT["status"])
    while s != expect and time.time() < deadline:
        time.sleep(0.7)
        s = state(ENT["status"])
    return s


def say(msg):
    print(msg, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pause", type=float, default=8, help="seconds to wait between steps (default 8)")
    ap.add_argument("--status", action="store_true", help="print tour-request flag and exit")
    a = ap.parse_args()

    if a.status:
        say(f"{ENT['flag']} = {state(ENT['flag'])}")
        return

    flag = state(ENT["flag"])
    say(f"tour-request flag: {flag}")

    dmin, dmax = num(ENT["dmin"]), num(ENT["dmax"])
    smin, rmin = num(ENT["smin"]), num(ENT["rmin"])
    say(f"thresholds: dir {dmin:.0f}–{dmax:.0f}°  speed ≥ {smin:g} kn  rain ≥ {rmin:g} mm/h")

    # snapshot values to restore at the end
    saved = {k: state(v) for k, v in (("dir", ENT["dir"]), ("spd", ENT["spd"]),
                                    ("rain", ENT["rain"]), ("sim", ENT["sim"]))}

    # danger direction = midpoint of the close arc (wrap-aware)
    if dmin <= dmax:
        danger_dir = (dmin + dmax) / 2
        safe_dir = (danger_dir + 180) % 360
    else:
        danger_dir = ((dmin + dmax + 360) / 2) % 360
        safe_dir = (danger_dir + 180) % 360
    danger_spd = smin + 3
    safe_spd = max(0.0, smin - 3)
    danger_rain = rmin + 2

    step = 0

    def banner(title):
        nonlocal step
        step += 1
        say(f"\n── Step {step}: {title}")

    try:
        banner("Simulation on — sliders drive the card")
        set_bool(ENT["sim"], True)
        set_num(ENT["rain"], 0)
        set_num(ENT["spd"], safe_spd)
        set_num(ENT["dir"], safe_dir)
        say(f"   wind {safe_dir:.0f}° (outside arc), {safe_spd:g} kn, rain 0 — baseline safe state")
        say(f"   status: {wait_status('Open shutter')} / state: {state(ENT['state'])}")
        time.sleep(a.pause)

        banner("Wind closes the shutter")
        set_num(ENT["dir"], danger_dir)
        set_num(ENT["spd"], danger_spd)
        say(f"   wind {danger_dir:.0f}° INSIDE red arc, {danger_spd:g} kn ≥ {smin:g} — watch needle turn red")
        s = wait_status("Close shutter")
        say(f"   status: {s} / state: {state(ENT['state'])}")
        time.sleep(a.pause)

        banner("Wind drops — shutter opens")
        set_num(ENT["spd"], safe_spd)
        say(f"   speed {safe_spd:g} kn < {smin:g} — needle back to green")
        s = wait_status("Open shutter")
        say(f"   status: {s} / state: {state(ENT['state'])}")
        time.sleep(a.pause)

        banner("Rain alone closes the shutter (OR logic)")
        set_num(ENT["dir"], safe_dir)
        set_num(ENT["rain"], danger_rain)
        say(f"   wind safe ({safe_dir:.0f}°, {safe_spd:g} kn) but rain {danger_rain:g} ≥ {rmin:g} mm/h")
        s = wait_status("Close shutter")
        say(f"   status: {s} / state: {state(ENT['state'])}")
        time.sleep(a.pause)

        banner("All clear — shutter opens")
        set_num(ENT["rain"], 0)
        s = wait_status("Open shutter")
        say(f"   status: {s} / state: {state(ENT['state'])}")
        time.sleep(a.pause)

        banner("Simulation off — live RK600 values return")
        set_bool(ENT["sim"], False)
        time.sleep(2)
        say(f"   live: dir {state(ENT['eff_dir'])}°, speed {state(ENT['eff_spd'])} kn, "
            f"rain {state(ENT['eff_rain'])} mm/h — status {state(ENT['status'])}")
        time.sleep(a.pause)
    finally:
        # restore pre-tour values + clear the request flag
        set_num(ENT["dir"], float(saved["dir"]))
        set_num(ENT["spd"], float(saved["spd"]))
        set_num(ENT["rain"], float(saved["rain"]))
        set_bool(ENT["sim"], saved["sim"] == "on")
        set_bool(ENT["flag"], False)
        say("\n── Done — restored pre-tour values, cleared dev_tour_request")


if __name__ == "__main__":
    main()
