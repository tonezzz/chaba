#!/usr/bin/env bash
# macbook-disable-hibernate — card tony-macbook-hibernate-resume-broken-eve-8ac607
#
# Option (a): drop hibernate on tony-macbook. Every suspend->hibernate cycle
# ends in a failed resume ("Unable to resume ... continuing boot process" +
# "PM: Image not found (code -22)") -> cold boot -> fleet-offline event until
# someone powers the machine on. Root cause evidence (2026-11-26):
#   - /swap.img has 22 extents across ~23.6G (kernel log at swap-on) — the
#     kernel resume path gets a single resume_offset and cannot locate the
#     image in a fragmented swapfile (known "Image not found" failure mode).
#   - s2idle suspend itself works (suspend entry/exit verified 2026-11-26).
#   - Prior fix attempts (fix-hibernate.sh x2, ~2026-10-20) did not resolve it.
#
# Change: /etc/systemd/logind.conf.d/hibernate.conf
#   HandleLidSwitch=suspend-then-hibernate  ->  suspend
# Battery lid-close then does plain s2idle suspend (reliable resume) instead
# of suspending into a hibernate that cannot resume. AC lid-close stays
# ignored via headless-crd.conf (HandleLidSwitchExternalPower=ignore), so the
# CRD/runner session is unaffected. Manual `systemctl hibernate` still exists
# but remains broken — do not use it.
#
# Run ON tony-macbook:   sudo bash scripts/ops/macbook-disable-hibernate.sh
# Revert: set HandleLidSwitch back to suspend-then-hibernate and re-run
# `sudo systemctl restart systemd-logind`.
#
# Idempotent: exits 0 without changes if already `suspend`.

set -euo pipefail

CONF=/etc/systemd/logind.conf.d/hibernate.conf
WANT='HandleLidSwitch=suspend'

if [ "$(id -u)" -ne 0 ]; then
    echo "error: must run as root (sudo bash $0)" >&2
    exit 1
fi

if grep -qE '^HandleLidSwitch=suspend$' "$CONF"; then
    echo "already disabled: $CONF has HandleLidSwitch=suspend"
    systemd-analyze cat-config systemd/logind.conf 2>/dev/null | grep -E 'HandleLidSwitch' || true
    exit 0
fi

cp -a "$CONF" "$CONF.bak-$(date +%Y%m%d-%H%M%S)"

cat > "$CONF" <<'EOF'
# hibernate dropped 2026-11-26 (card tony-macbook-hibernate-resume-broken-eve-8ac607):
# suspend->hibernate resume fails every cycle ("PM: Image not found"), cold-booting
# the host. Plain suspend keeps bag-safe sleep with a working resume path.
# Original backup: hibernate.conf.bak-<timestamp> in this directory.
[Login]
HandleLidSwitch=suspend
EOF

systemctl restart systemd-logind

echo "--- effective logind lid handling ---"
systemd-analyze cat-config systemd/logind.conf | grep -E 'HandleLidSwitch' || true
echo "done. Battery lid-close now suspends (s2idle); verify after next lid-close"
echo "with: journalctl -k -b | grep 'PM: suspend'  (expect entry+exit, no hibernate)"
