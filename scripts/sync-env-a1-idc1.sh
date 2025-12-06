#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
SSH_PORT=${SSH_PORT:-22}
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH to the private key file}"
: "${REMOTE_BASE:?Set REMOTE_BASE to the remote site root (e.g., /www/a1.idc-1.surf-thailand.com)}"
: "${ENV_DIR:?Set ENV_DIR to the folder containing env files}"
: "${APP:?Set APP to the app/site slug (e.g., a1-idc1)}"

ENV_FILE="$ENV_DIR/$APP.env"
TARGET_DIR="$REMOTE_BASE/$APP"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[sync-env] Missing env file: $ENV_FILE" >&2
  exit 1
fi

echo "[sync-env] Uploading $ENV_FILE -> $SSH_HOST:$TARGET_DIR/.env"

scp \
  -i "$SSH_KEY_PATH" \
  -P "${SSH_PORT}" \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "$ENV_FILE" \
  "$SSH_USER@$SSH_HOST:$TARGET_DIR/.env"

echo "[sync-env] Done"
