#!/usr/bin/env bash
# install-ssh-protect.sh — install the chaba-remote-protect drop-in for
# remote-access daemons on a target host (default: tony-dell).
#
# Applies systemd/dropins/chaba-remote-protect.conf to:
#   ssh.service         classic sshd daemon (owns :22 on tony-dell)
#   ssh@.service        per-connection template (inert if the package has none)
#   tailscaled.service  tailscale ssh/transport — restarting it kills the very
#                       ssh session driving this script, so it is restarted via
#                       a detached systemd-run unit, last.
#
# Usage: install-ssh-protect.sh [ssh-host]   # e.g. tony-dell | tony-dell-lan
set -euo pipefail

HOST="${1:-tony-dell}"
CONF="$(dirname "$(readlink -f "$0")")/../../systemd/dropins/chaba-remote-protect.conf"
UNITS="ssh.service ssh@.service tailscaled.service"

[ -f "$CONF" ] || { echo "missing $CONF" >&2; exit 1; }

for unit in $UNITS; do
    echo "== $HOST: $unit"
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" \
        "sudo -n mkdir -p '/etc/systemd/system/$unit.d'"
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" \
        "sudo -n tee '/etc/systemd/system/$unit.d/chaba-remote-protect.conf' >/dev/null" \
        < "$CONF"
done

ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" "sudo -n systemctl daemon-reload"

# ssh.service restart is safe: KillMode=process keeps existing sessions and
# chaba control sessions ride tailscaled ssh, not sshd.
ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" \
    "sudo -n systemctl restart ssh.service && echo 'ssh.service restarted'"

# tailscaled restart must outlive this ssh session (our control channel dies
# with it). Detach through a transient system unit.
ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" \
    "sudo -n systemd-run --system --unit=chaba-tailscaled-restart \
       -- sh -c 'sleep 2; systemctl restart tailscaled'"

echo "tailscaled restart scheduled (detached); waiting for it to come back..."
sleep 12
ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" \
    "systemctl is-active tailscaled ssh.service; \
     systemctl show ssh.service tailscaled.service \
       -p OOMScoreAdjust -p MemoryMin -p CPUWeight -p IOWeight -p Restart"
