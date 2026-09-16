#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$HOME/CascadeProjects/ada-pi}"
CHABA_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

mkdir -p "$HOME/.config/systemd/user"
mkdir -p "$HOME/.config/caddy"
mkdir -p "$HOME/.config/secrets"

# 1. Ensure Ada Pi repo is present and venv is ready
if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    git clone https://github.com/tonezzz/ada-pi.git "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"
git pull --ff-only || true

if [[ ! -x "$PROJECT_DIR/.venv/bin/uvicorn" ]]; then
    python3 -m venv "$PROJECT_DIR/.venv"
    "$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/backend/requirements.txt"
fi

# 2. Verify secrets are in place
missing=0
for secret in ada-ha-tony.env ada-ha-michael.env notebooklm-rest-api.env; do
    if [[ ! -f "$HOME/.config/secrets/$secret" ]]; then
        echo "ERROR: missing $HOME/.config/secrets/$secret" >&2
        missing=1
    fi
done
if [[ $missing -ne 0 ]]; then
    echo "Place the secrets on this host before installing." >&2
    exit 1
fi

# 3. Install systemd units
cp -v "$SCRIPT_DIR/ada-ha-tony.service" "$SCRIPT_DIR/ada-ha-michael.service" "$HOME/.config/systemd/user/"

# 4. Install Caddyfile
cp -v "$SCRIPT_DIR/Caddyfile.mn01" "$HOME/.config/caddy/Caddyfile.mn01"

# 5. Enable and start
cd "$CHABA_DIR"
systemctl --user daemon-reload
systemctl --user enable --now ada-ha-tony.service ada-ha-michael.service

if systemctl --user is-active caddy-mn01.service &>/dev/null; then
    systemctl --user reload-or-restart caddy-mn01.service
else
    echo "WARNING: caddy-mn01.service is not active. Start it and run:" >&2
    echo "  systemctl --user restart caddy-mn01.service" >&2
fi

echo "Ada HA Tony and Michael installed on $(hostname)."
