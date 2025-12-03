#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
SSH_PORT=${SSH_PORT:-22}
REMOTE_BASE=${REMOTE_BASE:-/www/node-1.h3.surf-thailand.com}
APP=${APP:?Set APP to the application name (e.g., site-sample)}
TARGET_RELEASE=${TARGET_RELEASE:-}

SSH_COMMON_OPTS=(
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)
if [[ -n "${SSH_KEY_PATH:-}" ]]; then
  SSH_COMMON_OPTS+=( -i "$SSH_KEY_PATH" )
fi

list_releases() {
  ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" \
    "cd '$REMOTE_BASE/$APP/releases' && ls -1t"
}

switch_release() {
  local release=$1
  cat <<'EOF' | ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST"
set -euo pipefail
APP="$APP"
REMOTE_BASE="$REMOTE_BASE"
RELEASE="$release"
TARGET_DIR="$REMOTE_BASE/$APP/releases/$RELEASE"
CURRENT_LINK="$REMOTE_BASE/$APP/current"
if [ ! -d "$TARGET_DIR" ]; then
  echo "Release $RELEASE does not exist" >&2
  exit 1
fi
ln -sfn "$TARGET_DIR" "$CURRENT_LINK"
if command -v plesk >/dev/null 2>&1; then
  plesk bin nodejs --restart node-1.h3.surf-thailand.com || true
fi
EOF
}

if [[ -z "$TARGET_RELEASE" ]]; then
  echo "Available releases for $APP:" >&2
  list_releases >&2
  echo "Set TARGET_RELEASE to one of the above" >&2
  exit 1
fi

switch_release "$TARGET_RELEASE"
echo "[DONE] Rolled $APP back to $TARGET_RELEASE"
