#!/usr/bin/env bash
# desktop-standard.sh — standard GNOME desktop prefs for Chaba hosts (idempotent).
#   1. Input sources: US + Thai xkb layouts (Super+Space switches — GNOME default).
# Extend this file as the "standard desktop" grows; new-host-onboarding.md
# calls it in step 1. User-level only, no sudo.
set -euo pipefail

cur=$(gsettings get org.gnome.desktop.input-sources sources 2>/dev/null || true)
if [ -z "$cur" ]; then
    echo "input-sources: no GNOME schema (not a GNOME host?) — skipped"
else
    case "$cur" in
        *"'th'"*) echo "input-sources: th already present ($cur)" ;;
        "[("*)   # non-empty list — append th, preserve any custom layouts
                 gsettings set org.gnome.desktop.input-sources sources \
                     "${cur%]}, ('xkb', 'th')]"
                 echo "input-sources: $cur -> ${cur%]}, ('xkb', 'th')]" ;;
        *)       gsettings set org.gnome.desktop.input-sources sources \
                     "[('xkb', 'us'), ('xkb', 'th')]"
                 echo "input-sources: set to [us, th]" ;;
    esac
fi
