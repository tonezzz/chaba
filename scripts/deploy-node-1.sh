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
RELEASES_TO_KEEP=${RELEASES_TO_KEEP:-5}

ENV_DIR=${ENV_DIR:-.secrets/node-1}
TIMESTAMP=${TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

release_dir() {
  local app=$1
  echo "$REMOTE_BASE/$app/releases/$TIMESTAMP"
}

current_link() {
  local app=$1
  echo "$REMOTE_BASE/$app/current"
}

ensure_release_dir() {
  local app=$1
  local dir=$(release_dir "$app")
  ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" "mkdir -p '$dir'"
}

rsync_app() {
  local app=$1
  local source_dir="$LOCAL_BASE/$app/"
  local target_dir=$(release_dir "$app")
  if [[ ! -d "$source_dir" ]]; then
    echo "[WARN] Local directory $source_dir not found, skipping"
    return
  fi
  ensure_release_dir "$app"
  echo "[SYNC] $source_dir -> $SSH_HOST:$target_dir"
  rsync -az --delete -e "ssh ${SSH_COMMON_OPTS[*]}" "$source_dir" "$SSH_USER@$SSH_HOST:$target_dir/"
}

install_remote() {
  local app=$1
  local target_dir=$(release_dir "$app")
  cat <<EOF | ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST"
set -euo pipefail
APP="$app"
TARGET_DIR="$target_dir"
cd "\$TARGET_DIR"
if [ -f package.json ]; then
  npm install --version >/dev/null 2>&1 || { echo "npm missing" >&2; exit 1; }
  echo "[REMOTE] npm install --production in \$TARGET_DIR"
  npm install --production --no-audit --no-fund
else
  echo "[REMOTE] package.json not found in \$TARGET_DIR, skipping npm install"
fi
EOF
}

validate_release() {
  local app=$1
  local target_dir
  target_dir=$(release_dir "$app")
  local required_paths=${RELEASE_REQUIRED_PATHS:-}
  cat <<'EOF' | SSH_USER="$SSH_USER" SSH_HOST="$SSH_HOST" TARGET_DIR="$target_dir" REQUIRED_PATHS="$required_paths" ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST"
set -euo pipefail
TARGET_DIR="${TARGET_DIR:?missing target dir}"
if [ ! -d "$TARGET_DIR" ]; then
  echo "[ERROR] Release directory missing: $TARGET_DIR" >&2
  exit 42
fi
if [ -z "$(find "$TARGET_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "[ERROR] Release directory empty: $TARGET_DIR" >&2
  exit 43
fi
if [ -n "$REQUIRED_PATHS" ]; then
  IFS=':' read -r -a paths <<<"$REQUIRED_PATHS"
  for rel_path in "${paths[@]}"; do
    if [ -n "$rel_path" ] && [ ! -e "$TARGET_DIR/$rel_path" ]; then
      echo "[ERROR] Required path missing in release: $TARGET_DIR/$rel_path" >&2
      exit 44
    fi
  done
fi
EOF
}

promote_release() {
  local app=$1
  local target_dir=$(release_dir "$app")
  local current=$(current_link "$app")
  local releases_root="$REMOTE_BASE/$app/releases"
  cat <<EOF | ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST"
set -euo pipefail
APP="$app"
TARGET_DIR="$target_dir"
CURRENT_LINK="$current"
RELEASES_ROOT="$releases_root"
ln -sfn "\$TARGET_DIR" "\$CURRENT_LINK"
if [ -d "\$RELEASES_ROOT" ]; then
  cd "\$RELEASES_ROOT"
  ls -1 | sort -r | tail -n +$((RELEASES_TO_KEEP + 1)) | xargs -r -I{} rm -rf "{}"
fi
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
  validate_release "$app"
  promote_release "$app"
done

restart_domain

echo "[DONE] Deployment pipeline finished"
