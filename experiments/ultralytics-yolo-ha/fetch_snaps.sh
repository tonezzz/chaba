#!/usr/bin/env bash
# Fetch bench snapshots. Run from experiments/ultralytics-yolo-ha/.
# Sources:
#   - vms-snap shim (XMEye CCTV) on mn01: GET /snap?ch=<name>, ~10-20s each, serial
#   - HA camera entities on tony-ha (tony-omen:8123), token from
#     ~/.config/secrets/home-assistant-token.env
# Note: michael-dev (idc03:8124) token in ~/.config/secrets/ha-michael-dev.env
# currently returns 401 — use tony-ha until that token is refreshed.
set -u
cd "$(dirname "$0")"

VMS="http://100.106.196.22:8377"
VMS_CHS=("1. Road In" "2. Guard View" "3. Walkway In" "4. Entrance Gate"
         "5. Road Corner" "Mini Mart" "Play Ground" "Swimming Pool"
         "Tennis Court" "Stairway Room" "Washing Machines"
         "Front Rd. Left" "Front Rd. Right")
# "D06" and "D10" are offline (red-X rows) — attach fails.

mkdir -p snaps
for ch in "${VMS_CHS[@]}"; do
  safe=$(echo "$ch" | tr ' .' '__')
  enc=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$ch")
  curl -s -m 120 -o "snaps/vms_${safe}.png" "$VMS/snap?ch=$enc"
  sleep 3   # shim is strictly serial; be polite
done

# HA camera entities that currently return real stills on tony-ha:
source "$HOME/.config/secrets/home-assistant-token.env"
for cam in omen_cam tony_dell_usb; do
  tok=$(curl -sk -m 10 -H "Authorization: Bearer $HA_LONG_LIVED_TOKEN" \
    "https://tony-omen.taila0626a.ts.net:8123/api/states/camera.$cam" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['attributes']['access_token'])")
  curl -sk -m 20 -o "snaps/ha_${cam}.jpg" \
    "https://tony-omen.taila0626a.ts.net:8123/api/camera_proxy/camera.${cam}?token=$tok"
done
# ip_cam_65 / xiaomi_c100* / xiaomi_c201_sd all 500 on camera_proxy (stills broken).
