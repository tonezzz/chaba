#!/usr/bin/env bash
# traffic-snap verify — health, registry count, one live snap.
# Usage: verify.sh [host]   (default: this host's tailscale ip)
set -euo pipefail

HOST="${1:-$(tailscale ip -4 | head -1)}"
BASE="http://$HOST:8378"

echo "== /health"
curl -sf "$BASE/health" | python3 -m json.tool

echo "== /channels (count)"
curl -sf "$BASE/channels" | python3 -c \
    'import json,sys; c=json.load(sys.stdin)["channels"]; print(len(c), "cameras"); [print(" ", n) for n in list(c)[:8]]'

echo "== /snap?ch=doh_vibhavadi"
out=$(mktemp --suffix=.jpg)
curl -sf -D - -o "$out" "$BASE/snap?ch=doh_vibhavadi" | grep -i "^x-camera\|^content-type" || true
file "$out"; ls -l "$out"
rm -f "$out"
