#!/usr/bin/env bash
# install-devin-host.sh — set up devin-desktop hardening on this host:
#   1. AppArmor userns profile (required on Ubuntu >= 24.04, where
#      kernel.apparmor_restrict_unprivileged_userns=1 otherwise denies the
#      Electron sandbox -> renderer SIGTRAP crashes).
#   2. devin-desktop-watchdog.sh -> ~/.local/bin + cron every 10 min.
#
# Usage: bash scripts/devin/install-devin-host.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- AppArmor profile ---------------------------------------------------------
restrict="$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)"
if [ "$restrict" = "1" ]; then
    if command -v apparmor_parser >/dev/null 2>&1; then
        sudo install -m 0644 "$DIR/apparmor-devin-desktop" /etc/apparmor.d/devin-desktop
        sudo apparmor_parser -r /etc/apparmor.d/devin-desktop
        echo "apparmor: devin-desktop userns profile installed and loaded"
    else
        echo "apparmor: apparmor_parser not found; skipping (install apparmor first)" >&2
    fi
else
    echo "apparmor: unprivileged userns restriction is off; profile not needed"
fi

# --- Watchdog -----------------------------------------------------------------
install -m 0755 "$DIR/devin-desktop-watchdog.sh" "$HOME/.local/bin/devin-desktop-watchdog.sh"
entry='*/10 * * * * $HOME/.local/bin/devin-desktop-watchdog.sh'
if ! crontab -l 2>/dev/null | grep -q 'devin-desktop-watchdog.sh'; then
    (crontab -l 2>/dev/null; echo "*/10 * * * * $HOME/.local/bin/devin-desktop-watchdog.sh") | crontab -
    echo "watchdog: installed and cron entry added"
else
    echo "watchdog: installed (cron entry already present)"
fi

echo "done. Optional: touch ~/.config/devin/watchdog-autorestart to enable auto-restart."
