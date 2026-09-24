#!/usr/bin/env bash
# Install/refresh the xmeye-vms quadlet on THIS host.
# Usage: bash install.sh [bind-ip]   (default: this host's tailscale IPv4)
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$HOME/.local/share/xmeye-vms"
BIND_IP="${1:-}"

if [[ -z "$BIND_IP" ]]; then
    BIND_IP="$(tailscale ip -4 2>/dev/null || true)"
fi
if [[ -z "$BIND_IP" ]]; then
    echo "ERROR: no bind IP given and 'tailscale ip -4' returned nothing." >&2
    exit 1
fi

# 1. State dirs — contents are NOT managed here; rsync them from the source host
#    (see README.md "Moving the service"). Only start-vms.sh is kept current.
mkdir -p "$STATE_DIR/vms-runtime" "$STATE_DIR/wineprefix" \
         "$HOME/.config/containers/systemd"

if [[ ! -f "$STATE_DIR/vms-runtime/VMS.exe" ]]; then
    echo "WARNING: $STATE_DIR/vms-runtime/VMS.exe missing — rsync state from the source host first." >&2
fi

if ! podman image exists localhost/xmeye-vms-x11vnc:latest; then
    echo "ERROR: image localhost/xmeye-vms-x11vnc:latest not present." >&2
    echo "  podman save ... | ssh <host> 'podman load'   (see README.md)" >&2
    exit 1
fi

install -m 0755 "$SCRIPT_DIR/start-vms.sh" "$STATE_DIR/vms-runtime/start-vms.sh"

# 2. Quadlet — render PublishPort for this host's bind IP.
sed "s/^PublishPort=.*/PublishPort=${BIND_IP}:5900:5900/" \
    "$SCRIPT_DIR/xmeye-vms.container" \
    > "$HOME/.config/containers/systemd/xmeye-vms.container"

systemctl --user daemon-reload
# Quadlet units are generated: [Install] WantedBy=default.target is honored by the
# generator itself, so the service autostarts at login — plain `start`, no `enable`.
systemctl --user start xmeye-vms.service

echo "xmeye-vms installed on $(hostname), VNC bound to ${BIND_IP}:5900"
