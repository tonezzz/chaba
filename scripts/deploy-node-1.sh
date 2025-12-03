#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
SSH_PORT=${SSH_PORT:-22}

push_env() {
  local app=$1
  local env_file="$ENV_DIR/$app.env"
  local target_dir="$REMOTE_BASE/$app"
  if [[ -f "$env_file" ]]; then
    echo "[SYNC] uploading env for $app"
    scp "${SSH_COMMON_OPTS[@]}" "$env_file" "$SSH_USER@$SSH_HOST:$target_dir/.env"
  else
    echo "[INFO] no env file for $app in $ENV_DIR"
  fi
}
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH to the private key file}"
REMOTE_BASE=${REMOTE_BASE:-/www/node-1.h3.surf-thailand.com}
LOCAL_BASE=${LOCAL_BASE:-sites}
APPS=${APPS:-"site-sample site-logger"}

ENV_DIR=${ENV_DIR:-.secrets/node-1}

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

rsync_app() {
  local app=$1
  local source_dir="$LOCAL_BASE/$app/"
  local target_dir="$REMOTE_BASE/$app/"
  if [[ ! -d "$source_dir" ]]; then
    echo "[WARN] Local directory $source_dir not found, skipping"
    return
  fi
  echo "[SYNC] $source_dir -> $SSH_HOST:$target_dir"
  rsync -az --delete -e "ssh ${SSH_COMMON_OPTS[*]}" "$source_dir" "$SSH_USER@$SSH_HOST:$target_dir"
}

install_remote() {
  local app=$1
  local target_dir="$REMOTE_BASE/$app"
  cat <<'EOF' | ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST"
set -euo pipefail
APP="$app"
TARGET_DIR="$target_dir"
cd "$TARGET_DIR"
echo "[REMOTE] npm install --production in $TARGET_DIR"
npm install --production --no-audit --no-fund
EOF
}

restart_domain() {
  ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" <<'EOF'
set -euo pipefail
if command -v plesk >/dev/null 2>&1; then
  echo "[REMOTE] Restarting Node app via Plesk"
  plesk bin nodejs --restart node-1.h3.surf-thailand.com || true
else
  echo "[REMOTE] Plesk CLI not found; skipping restart"
fi
EOF
}

for app in $APPS; do
  rsync_app "$app"
  push_env "$app"
  install_remote "$app"
done

restart_domain

echo "[DONE] Deployment pipeline finished"
