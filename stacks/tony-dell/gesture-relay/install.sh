#!/usr/bin/env bash
# Install/refresh the gesture-relay quadlet on THIS host.
# Usage: bash install.sh [bind-ip]   (default: this host's tailscale IPv4)
#
# 1. build the image:  podman build -t localhost/gesture-relay:latest \
#        stacks/tony-dell/gesture-relay
# 2. bash install.sh   (renders PublishPort, daemon-reload, start)
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIND_IP="${1:-}"

if [[ -z "$BIND_IP" ]]; then
    BIND_IP="$(tailscale ip -4 2>/dev/null || true)"
fi
if [[ -z "$BIND_IP" ]]; then
    echo "ERROR: no bind IP given and 'tailscale ip -4' returned nothing." >&2
    exit 1
fi

if ! podman image exists localhost/gesture-relay:latest; then
    echo "ERROR: image localhost/gesture-relay:latest not present." >&2
    echo "  podman build -t localhost/gesture-relay:latest $SCRIPT_DIR" >&2
    exit 1
fi

mkdir -p "$HOME/.config/containers/systemd"

# Render PublishPort for this host's bind IP — tailnet-only, never LAN.
sed "s/^PublishPort=.*/PublishPort=${BIND_IP}:8794:8794/" \
    "$SCRIPT_DIR/gesture-relay.container" \
    > "$HOME/.config/containers/systemd/gesture-relay.container"

systemctl --user daemon-reload
# Quadlet units are generated; [Install] WantedBy=default.target is honored
# by the generator — plain `start`, no `enable`.
systemctl --user restart gesture-relay.service

sleep 2
curl -sf "http://${BIND_IP}:8794/health" && echo " <- gesture-relay health ok"
