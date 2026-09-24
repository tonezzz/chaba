#!/usr/bin/env bash
set -euo pipefail

echo "== systemd unit =="
systemctl --user is-active xmeye-vms.service

echo "== container =="
podman ps --filter name=xmeye-vms-vnc --format '{{.Names}} {{.Status}} {{.Ports}}'

echo "== VNC listener =="
ss -tln | grep 5900

echo "== RFB handshake =="
BIND_IP="$(tailscale ip -4 2>/dev/null || echo 127.0.0.1)"
timeout 5 bash -c "exec 3<>/dev/tcp/${BIND_IP}/5900 && head -c 12 <&3" | tr -d '\0'; echo

echo "== processes in container =="
podman exec xmeye-vms-vnc ps -eo comm,pid 2>/dev/null | grep -E 'Xvfb|x11vnc|VMS|explorer' || echo "VMS.exe not running yet (cold wineprefix can take a minute)"

echo "Verify complete."
