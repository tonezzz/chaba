#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="$HOME/.local/ai-hub"
CONFIG_DIR="$HOME/.config/ai-hub"
SERVICE_DIR="$HOME/.config/systemd/user"

mkdir -p "$LOCAL_DIR" "$CONFIG_DIR" "$SERVICE_DIR"
cp "$SCRIPT_DIR/cookie-bridge.mjs" "$LOCAL_DIR/"
cp "$SCRIPT_DIR/cookie-bridge.service" "$SERVICE_DIR/"

if [ ! -f "$CONFIG_DIR/cookie-bridge.env" ]; then
  cp "$SCRIPT_DIR/cookie-bridge.env.example" "$CONFIG_DIR/cookie-bridge.env"
  echo "Created $CONFIG_DIR/cookie-bridge.env. Please edit it before starting."
else
  echo "$CONFIG_DIR/cookie-bridge.env already exists, leaving unchanged."
fi

systemctl --user daemon-reload
systemctl --user enable cookie-bridge
echo "cookie-bridge enabled. Start it with: systemctl --user start cookie-bridge"
