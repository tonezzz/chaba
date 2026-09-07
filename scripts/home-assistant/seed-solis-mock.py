#!/usr/bin/env python3
"""Seed michael-dev with michael-ha's current states for any entity that is
unavailable/unknown/missing on dev. Used to make the TPL_SOLIS (Solar
Assistant copy) view show realistic mock values.

Usage:
    seed-solis-mock.py [--all] [--entities-file FILE]

- Default entity list: every sensor.* referenced by the embedded Solar
  Assistant view definition (kept in sync with the tpl_solis view).
- --all: also seed sensors referenced by any other dev-only view that has
  unavailable entities (future use).
- Reads tokens from:
    dev:  ~/.config/secrets/ha-michael-dev.env (HASS_TOKEN)
    live: ~/.local/share/home-assistant-michael/ha-token

States are in-memory only — rerun after any michael-dev restart.
"""
import json
import os
import sys
import urllib.request

DEV_URL = os.environ.get(
    "DEV_URL", "https://tony-dell.taila0626a.ts.net:8124"
)
HA_URL = os.environ.get("HA_URL", "http://michael-ha:8123")
DEV_TOKEN = os.environ["HASS_TOKEN"]
HA_TOKEN = open(
    os.path.expanduser("~/.local/share/home-assistant-michael/ha-token")
).read().strip()

# Entities referenced by the TPL_SOLIS (Solar Assistant) view.
SOLIS_ENTITIES = [
    "sensor.inverters_1_pv_power",
    "sensor.inverters_1_pv_power_1",
    "sensor.inverters_1_pv_power_2",
    "sensor.inverters_1_pv_voltage_1",
    "sensor.inverters_1_pv_voltage_2",
    "sensor.inverters_1_pv_current_1",
    "sensor.inverters_1_pv_current_2",
    "sensor.inverters_1_battery_power",
    "sensor.inverters_1_battery_voltage",
    "sensor.inverters_1_battery_current",
    "sensor.inverters_1_battery_state_of_charge",
    "sensor.inverters_1_battery_state_of_health",
    "sensor.inverters_1_load_power",
    "sensor.inverters_1_load_power_essential",
    "sensor.inverters_1_grid_power",
    "sensor.inverters_1_grid_voltage",
    "sensor.inverters_1_grid_frequency",
    "sensor.inverters_1_inverter_mode",
    "sensor.inverters_1_temperature",
    "sensor.solis_s6_eh3p10k_h_zp_today_energy_consumption",
    "sensor.solis_s6_eh3p10k_h_zp_today_energy_imported_from_grid",
    "sensor.solis_s6_eh3p10k_h_zp_today_energy_fed_into_grid",
    "sensor.solis_s6_eh3p10k_h_zp_today_battery_charge_energy",
    "sensor.solis_s6_eh3p10k_h_zp_today_battery_discharge_energy",
    "sensor.solis_s6_eh3p10k_h_zp_ac_coupling_today_power_generation",
]
for n in (1, 2, 3):
    SOLIS_ENTITIES += [
        f"sensor.batteries_{n}_power",
        f"sensor.batteries_{n}_state_of_charge",
        f"sensor.batteries_{n}_voltage",
        f"sensor.batteries_{n}_current",
        f"sensor.batteries_{n}_cell_voltage_average",
        f"sensor.batteries_{n}_cell_voltage_highest",
        f"sensor.batteries_{n}_cell_voltage_lowest",
        f"sensor.batteries_{n}_cell_voltage_imbalance",
        f"sensor.batteries_{n}_temperature",
        f"sensor.batteries_{n}_temperature_1",
        f"sensor.batteries_{n}_temperature_2",
        f"sensor.batteries_{n}_temperature_mos",
        f"sensor.batteries_{n}_cycles",
        f"sensor.batteries_{n}_state_of_health",
    ]


def get(url, token, entity):
    req = urllib.request.Request(
        f"{url}/api/states/{entity}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        return json.load(urllib.request.urlopen(req))
    except Exception:
        return None


def post(entity, state, attrs):
    body = json.dumps({"state": state, "attributes": attrs}).encode()
    req = urllib.request.Request(
        f"{DEV_URL}/api/states/{entity}",
        data=body,
        headers={
            "Authorization": f"Bearer {DEV_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req)
        return True
    except Exception as ex:
        print(f"  FAIL {entity}: {ex}")
        return False


def main():
    ents = SOLIS_ENTITIES
    if "--entities-file" in sys.argv:
        ents = json.load(open(sys.argv[sys.argv.index("--entities-file") + 1]))
    copied, skipped, nolive = 0, 0, []
    for e in ents:
        d = get(DEV_URL, DEV_TOKEN, e)
        if d and d["state"] not in ("unavailable", "unknown"):
            skipped += 1
            continue
        h = get(HA_URL, HA_TOKEN, e)
        if h and h["state"] not in ("unavailable", "unknown"):
            if post(e, h["state"], h.get("attributes", {})):
                copied += 1
        else:
            nolive.append(e)
    print(f"seeded {copied} | already-live {skipped} | no live value {len(nolive)}")
    for e in nolive:
        print("  nolive:", e)


if __name__ == "__main__":
    main()
