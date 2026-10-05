#!/usr/bin/env bash
# traffic-snap installer — copies the shim to ~/.local/share/traffic-cam/,
# renders the tailnet-only bind into the user unit, enables it.
# Same pattern as stacks/services/xmeye-vms/install.sh.
#
# Usage: install.sh [--repo <path-to-chaba-checkout>]
#   --repo defaults to ~/CascadeProjects/chaba-tony-dell (the live checkout
#   that owns frigate/cameras.json — the camera registry SSOT).
set -euo pipefail

STACK="$(cd "$(dirname "$0")" && pwd)"
REPO="${TRAFFIC_SNAP_REPO:-$HOME/CascadeProjects/chaba-tony-dell}"
while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO="$2"; shift 2;;
        *) echo "unknown arg: $1" >&2; exit 2;;
    esac
done

TS_IP="$(tailscale ip -4 | head -1)"
[ -n "$TS_IP" ] || { echo "no tailscale ip" >&2; exit 1; }
[ -f "$REPO/frigate/cameras.json" ] \
    || { echo "no registry at $REPO/frigate/cameras.json — pass --repo" >&2
         exit 1; }

mkdir -p ~/.local/share/traffic-cam ~/.config/systemd/user
cp "$STACK/traffic-snap.py" ~/.local/share/traffic-cam/traffic-snap.py
sed -e "s/__TAILIP__/$TS_IP/" \
    -e "s|%h/CascadeProjects/chaba-tony-dell|$REPO|" \
    "$STACK/traffic-snap.service" \
    > ~/.config/systemd/user/traffic-snap.service

systemctl --user daemon-reload
systemctl --user enable --now traffic-snap.service
systemctl --user is-active traffic-snap.service
echo "traffic-snap on http://$TS_IP:8378"
