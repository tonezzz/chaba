#!/usr/bin/env bash
set -euo pipefail

SOURCE_HOST="${1:-mn01}"
BACKUP_HOST="${2:-tony-dell}"

TS="$(date +%Y%m%d-%H%M%S)"
REMOTE_BACKUP_DIR="$HOME/.local/share/backups/mn01"
REMOTE_TS_DIR="$REMOTE_BACKUP_DIR/$TS"

ssh -o ConnectTimeout=10 "$BACKUP_HOST" "mkdir -p \"$REMOTE_TS_DIR/config\" \"$REMOTE_TS_DIR/secrets\" && chmod 700 \"$REMOTE_TS_DIR\""

# Copy live config (no secrets)
scp -3 "$SOURCE_HOST:$HOME/.config/systemd/user/ada-ha-tony.service" "$BACKUP_HOST:$REMOTE_TS_DIR/config/"
scp -3 "$SOURCE_HOST:$HOME/.config/systemd/user/ada-ha-michael.service" "$BACKUP_HOST:$REMOTE_TS_DIR/config/"
scp -3 "$SOURCE_HOST:$HOME/.config/caddy/Caddyfile.mn01" "$BACKUP_HOST:$REMOTE_TS_DIR/config/"

# Copy secrets to the remote backup host (assumes that host is trusted and user-secured)
scp -3 "$SOURCE_HOST:$HOME/.config/secrets/ada-ha-tony.env" "$BACKUP_HOST:$REMOTE_TS_DIR/secrets/"
scp -3 "$SOURCE_HOST:$HOME/.config/secrets/ada-ha-michael.env" "$BACKUP_HOST:$REMOTE_TS_DIR/secrets/"
scp -3 "$SOURCE_HOST:$HOME/.config/secrets/notebooklm-rest-api.env" "$BACKUP_HOST:$REMOTE_TS_DIR/secrets/"

# Manifest
cat <<EOF | ssh "$BACKUP_HOST" "cat > \"$REMOTE_TS_DIR/manifest.txt\""
source: $SOURCE_HOST
backup_host: $BACKUP_HOST
timestamp: $TS
files:
  config/ada-ha-tony.service
  config/ada-ha-michael.service
  config/Caddyfile.mn01
  secrets/ada-ha-tony.env
  secrets/ada-ha-michael.env
  secrets/notebooklm-rest-api.env
EOF

ssh "$BACKUP_HOST" "cd \"$REMOTE_BACKUP_DIR\" && rm -f latest && ln -s \"$TS\" latest"

echo "mn01 Ada HA backed up to $BACKUP_HOST:$REMOTE_TS_DIR"
