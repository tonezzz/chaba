#!/usr/bin/env bash
# Print the unlock deep-link for an Ada backend: <public-url>?api_key=<key>
# The key is read from the service env file on its host — never stored here.
# With --qr, mints a one-time redeem URL instead (burns on use, expires in
# ADA_REDEEM_TTL_S) — a leaked QR/screenshot is useless after one scan.
# Usage: ada-key-url.sh <tony|michael|ada-pi>   (add --qr to render a QR code)
set -euo pipefail

instance="${1:-}"; want_qr="${2:-}"
case "$instance" in
  tony)    host=mn01;      env_name=ada-ha-tony.env;    base=https://mn01.taila0626a.ts.net/apps/ada_ha_tony/ ;;
  michael) host=mn01;      env_name=ada-ha-michael.env; base=https://mn01.taila0626a.ts.net/apps/ada_ha_michael/ ;;
  ada-pi)  host=tony-dell; env_name=ada-pi-pwa.env;     base=https://tony-dell.taila0626a.ts.net/apps/ada_pi/ ;;
  *) echo "usage: $0 <tony|michael|ada-pi> [--qr]" >&2; exit 2 ;;
esac

key="$(ssh "$host" "grep -oP '(?<=^ADA_API_KEY=).*' ~/.config/secrets/$env_name")"
if [[ -z "$key" ]]; then
  echo "no ADA_API_KEY in $host:~/.config/secrets/$env_name" >&2
  exit 1
fi

origin="${base%%/apps/*}"
path="${base#"$origin"}"; path="${path%/}"

if [[ "$want_qr" == "--qr" ]]; then
  resp="$(curl -fsS --max-time 10 -X POST "${base}api/auth/redeem-token" \
    -H "x-api-key: ${key}" -H 'content-type: application/json' \
    -d "{\"path\": \"${path}\"}")" || { echo "redeem-token request failed" >&2; exit 1; }
  read -r rel ttl < <(python3 -c \
    'import json,sys; r=json.load(sys.stdin); print(r["redeem_url"], r["expires_in"])' <<< "$resp")
  url="${origin}${rel}"
  echo "$url"
  echo "(one-time redeem link — burns on first use, expires in ${ttl}s)" >&2
else
  url="${base}?api_key=${key}"
  echo "$url"
fi

if [[ "$want_qr" == "--qr" ]]; then
  if command -v qrencode >/dev/null 2>&1; then
    qrencode -t ANSIUTF8 "$url"
  else
    echo "(qrencode not installed — sudo apt install qrencode)" >&2
  fi
fi
