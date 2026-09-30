#!/usr/bin/env bash
# camwall-edge installer — renders the tailnet-only PublishPort and links
# the quadlet + env into systemd user units.
set -euo pipefail

STACK="$(cd "$(dirname "$0")" && pwd)"
TS_IP="$(tailscale ip -4 | head -1)"
[ -n "$TS_IP" ] || { echo "no tailscale ip" >&2; exit 1; }

mkdir -p ~/.config/containers/systemd ~/.config/camwall-edge \
         ~/.local/share/camwall
cp "$STACK/Caddyfile" ~/.config/camwall-edge/Caddyfile
sed "s/__TAILIP__/$TS_IP/" "$STACK/camwall-edge.container" \
    > ~/.config/containers/systemd/camwall-edge.container

systemctl --user daemon-reload
systemctl --user enable --now camwall-edge.service
systemctl --user is-active camwall-edge.service
echo "camwall-edge on http://$TS_IP:8380"
