#!/bin/sh
# Fetch PV1/PV2/Grid/Battery/Load values from michael-dev and write a tiny
# text file for the ESP32 display.
# Output format (one value per line):
#   pv1_power pv1_voltage pv1_current
#   pv2_power pv2_voltage pv2_current
#   grid_power grid_voltage grid_frequency
#   bat_soc_avg bat_power_sum load_power
set -eu
. "$HOME/.config/secrets/home-assistant-token.env"
OUT="${1:-$HOME/CascadeProjects/chaba-tony-dell/stacks/web/public/snapshots/pv1.txt}"
HA="http://127.0.0.1:8124"

get() {
  curl -sf -m 8 -H "Authorization: Bearer $HA_LONG_LIVED_TOKEN" \
    "$HA/api/states/$1" | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])"
}

BAT=$(curl -sf -m 8 -H "Authorization: Bearer $HA_LONG_LIVED_TOKEN" \
  "$HA/api/states" | python3 -c "
import json,sys
d={s['entity_id']:s['state'] for s in json.load(sys.stdin)}
socs=[float(d[f'sensor.batteries_{i}_state_of_charge']) for i in (1,2,3)]
pows=[float(d[f'sensor.batteries_{i}_power']) for i in (1,2,3)]
print(sum(socs)/3.0)
print(sum(pows))")

TMP=$(mktemp "$OUT.XXXXXX")
{
  get sensor.inverters_1_pv_power_1
  get sensor.inverters_1_pv_voltage_1
  get sensor.inverters_1_pv_current_1
  get sensor.inverters_1_pv_power_2
  get sensor.inverters_1_pv_voltage_2
  get sensor.inverters_1_pv_current_2
  get sensor.inverters_1_grid_power
  get sensor.inverters_1_grid_voltage
  get sensor.inverters_1_grid_frequency
  echo "$BAT"
  get sensor.inverters_1_load_power
} > "$TMP"
mv "$TMP" "$OUT"
echo "wrote $OUT:"
cat "$OUT"
