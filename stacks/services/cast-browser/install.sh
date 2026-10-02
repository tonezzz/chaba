#!/usr/bin/env bash
# Install cast-browser stack on tony-omen:
#   cast-browser-server.mjs  -> ~/.local/bin/
#   cast-browser.service     -> ~/.config/systemd/user/
#   cast-desktop@.service    -> ~/.config/systemd/user/
#   cast-shots-http.service  -> ~/.config/systemd/user/
# Run on tony-omen. Restart is left to the caller — see README.
set -euo pipefail
cd "$(dirname "$0")"

install -m 755 cast-browser-server.mjs ~/.local/bin/cast-browser-server.mjs
install -m 755 cast-desktop-run.sh    ~/.local/bin/cast-desktop-run.sh
install -m 644 cast-browser.service   ~/.config/systemd/user/cast-browser.service
install -m 644 'cast-desktop@.service' ~/.config/systemd/user/'cast-desktop@.service'
install -m 644 cast-shots-http.service ~/.config/systemd/user/cast-shots-http.service

systemctl --user daemon-reload
echo "installed — restart with: systemctl --user restart cast-browser"
