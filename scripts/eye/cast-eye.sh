#!/usr/bin/env bash
# cast-eye.sh — put /apps/eye/ (in-browser detection overlay) on a display.
#
# Lanes:
#   cast-eye.sh screen <N> [params]   vcast nav — the display's own
#     browser loads the page live in an iframe and runs the detector
#     (true edge compute). Any paired vcast screen; lab screens are 6/7.
#   cast-eye.sh tv [workspace] [params]
#     Real TV (tony_tv_cast): opens a fullscreen Chrome on tony-omen
#     workspace N over ssh, then casts that workspace live via
#     cast-browser `nav tony-omen:workspace:N` (cast-desktop@0 x11grab ->
#     HLS -> HA camera.play_stream). Detection runs in omen's desktop
#     Chrome — the TV shows the overlay as video.
#   cast-eye.sh stop screen <N> | tv    stop the cast.
#
# eye params default: src=test&pub=10 (synthetic frames + detections
# published for ada_look). Examples: "src=cam:doh_vibhavadi&pub=10",
# "src=vms:Guard%20View&pub=10", "src=snap:vms-noble-a/road-in&pub=10".
# NOTE: src=me (getUserMedia) does NOT work inside a vcast nav iframe
# (no camera permission) nor headless — use it on a real seat only.
#
# Env: CAST_BROWSER_URL (default http://100.75.102.88:8799),
#      INPUT_BRIDGE (default https://tony-dell.taila0626a.ts.net/api/input-bridge),
#      EYE_BASE (default https://tony-dell.taila0626a.ts.net/apps/eye/),
#      SPEAKER (default tony — cast-browser ACL needs an owner identity
#      for desktop/workspace lanes).

set -euo pipefail

CAST_BROWSER_URL="${CAST_BROWSER_URL:-http://100.75.102.88:8799}"
INPUT_BRIDGE="${INPUT_BRIDGE:-https://tony-dell.taila0626a.ts.net/api/input-bridge}"
EYE_BASE="${EYE_BASE:-https://tony-dell.taila0626a.ts.net/apps/eye/}"
SPEAKER="${SPEAKER:-tony}"
OMEN_SSH="${OMEN_SSH:-tony-omen}"
OMEN_DISPLAY="${OMEN_DISPLAY:-:0}"

usage() { sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

eye_url() { echo "${EYE_BASE}?${1:-src=test&pub=10}"; }

cmd="${1:-}"; shift || true
[ -z "$cmd" ] && usage

case "$cmd" in
screen)
  n="${1:?screen number}"; shift || true
  url="$(eye_url "${1:-}")"
  echo "vcast nav screen $n -> $url"
  curl -sf -X POST "$INPUT_BRIDGE/pub" -H 'Content-Type: application/json' \
    -d "{\"screen\":$n,\"msg\":{\"type\":\"nav\",\"url\":\"$url\"}}"
  echo
  echo "verify: curl -s $INPUT_BRIDGE/displays | jq '.[] | select(.screen==$n)'"
  ;;

tv)
  ws="${1:-4}"; shift || true
  url="$(eye_url "${1:-}")"
  echo "open on $OMEN_SSH workspace $ws ($OMEN_DISPLAY): $url"
  # workspace index is 0-based for xdotool
  idx=$((ws - 1))
  ssh "$OMEN_SSH" "DISPLAY=$OMEN_DISPLAY xdotool set_desktop $idx && \
    DISPLAY=$OMEN_DISPLAY nohup google-chrome --new-window \
    --start-fullscreen '$url' >/dev/null 2>&1 & sleep 1; echo launched"
  echo "cast workspace $ws -> TV via screenlive lane"
  curl -sf -X POST "$CAST_BROWSER_URL/nav" -H 'Content-Type: application/json' \
    -d "{\"url\":\"tony-omen:workspace:$ws\",\"speaker\":\"$SPEAKER\"}"
  echo
  ;;

stop)
  case "${1:-tv}" in
    screen)
      n="${2:?screen number}"
      curl -sf -X POST "$INPUT_BRIDGE/pub" -H 'Content-Type: application/json' \
        -d "{\"screen\":$n,\"msg\":{\"type\":\"stop\"}}"
      echo " -> screen $n stopped"
      ;;
    tv)
      curl -sf -X POST "$CAST_BROWSER_URL/nav" -H 'Content-Type: application/json' \
        -d "{\"url\":\"off\",\"speaker\":\"$SPEAKER\"}"
      echo " -> tv cast stopped"
      ;;
    *) usage ;;
  esac
  ;;

*) usage ;;
esac
