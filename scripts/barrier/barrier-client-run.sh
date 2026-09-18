#!/usr/bin/env bash
# barrierc launcher for tony-dell.
# Prefers the LAN path to tony-omen when on the home network (192.168.2.0/24),
# falls back to Tailscale otherwise. Re-evaluated on every service restart.
set -u

LAN_ADDR="192.168.2.86"
TS_ADDR="100.75.102.88"
PORT=24800

on_home_net() {
    ip -4 -o addr show scope global | grep -q '192\.168\.2\.[0-9]*/24'
}

if on_home_net && nc -z -w2 "$LAN_ADDR" "$PORT" 2>/dev/null; then
    SERVER="$LAN_ADDR"
else
    SERVER="$TS_ADDR"
fi

echo "barrier-client-run: connecting to $SERVER" >&2
exec /home/tony/.local/bin/barrierc --no-daemon --disable-crypto \
    --name tony-dell --log /tmp/barrier-client.log "$SERVER"
