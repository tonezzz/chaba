#!/usr/bin/env bash
# Restart barrier-client.service if it is connected via the wrong path
# for the current network. Home LAN -> must use 192.168.2.86, else Tailscale.
set -u

LAN_ADDR="192.168.2.86"
TS_ADDR="100.75.102.88"

on_home_net() {
    ip -4 -o addr show scope global | grep -q '192\.168\.2\.[0-9]*/24'
}

# Peer the client is currently connected to on port 24800, if any.
peer="$(ss -tnH state established 2>/dev/null | awk '$5 ~ /:24800$/ {print $5}' | cut -d: -f1 | head -1)"
[ -z "$peer" ] && exit 0

if on_home_net && [ "$peer" = "$TS_ADDR" ]; then
    echo "barrier-enforce: on home LAN but connected via Tailscale ($peer); restarting client"
    systemctl --user restart barrier-client.service
elif ! on_home_net && [ "$peer" = "$LAN_ADDR" ]; then
    echo "barrier-enforce: off home LAN but connected via LAN addr ($peer); restarting client"
    systemctl --user restart barrier-client.service
fi
