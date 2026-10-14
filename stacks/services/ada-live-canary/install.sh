#!/usr/bin/env bash
# Install the Gemini lane canaries on idc03 (user units):
#   ada-live-canary.timer        hourly :17 — FREE key connect (ceiling map)
#   ada-live-canary-paid.timer   daily 06:12 — PAID key connect (1/day)
#   gemini-wallet-watch.timer    hourly :47 — ~1-token PAID REST ping +
#                                LINE alert on wallet transitions
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

mkdir -p ~/.config/systemd/user
cp "$HERE"/ada-live-canary.service "$HERE"/ada-live-canary.timer \
   "$HERE"/ada-live-canary-paid.service "$HERE"/ada-live-canary-paid.timer \
   "$HERE"/gemini-wallet-watch.service "$HERE"/gemini-wallet-watch.timer \
   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now \
    ada-live-canary.timer \
    ada-live-canary-paid.timer \
    gemini-wallet-watch.timer
echo "installed — timers: systemctl --user list-timers | grep -E 'canary|wallet'"
