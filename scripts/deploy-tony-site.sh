#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}
REMOTE_BASE=${REMOTE_BASE:-/www/node-1.h3.surf-thailand.com}
LOCAL_TONY_ROOT=${LOCAL_TONY_ROOT:-sites/tony/sites}
REMOTE_TONY_ROOT=${REMOTE_TONY_ROOT:-$REMOTE_BASE/site-man/current/tony/sites}
NODE_DOMAIN=${NODE_DOMAIN:-node-1.h3.surf-thailand.com}

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

declare -a SITES=()

if [[ $# -gt 0 ]]; then
  SITES=($(printf '%s\n' "$@"))
elif [[ -n "${TONY_SITES:-}" ]]; then
  # shellcheck disable=SC2206 # intentional word splitting on env value
  SITES=($TONY_SITES)
elif [[ -d "$LOCAL_TONY_ROOT" ]]; then
  while IFS= read -r -d '' entry; do
    SITES+=("$(basename "$entry")")
  done < <(find "$LOCAL_TONY_ROOT" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
fi

if [[ ${#SITES[@]} -eq 0 ]]; then
  echo "[ERROR] No Tony site folders were found under $LOCAL_TONY_ROOT" >&2
  exit 1
fi

sync_site() {
  local site=$1
  local source_dir="$LOCAL_TONY_ROOT/$site"
  local target_dir="$REMOTE_TONY_ROOT/$site"

  if [[ ! -d "$source_dir" ]]; then
    echo "[WARN] Skipping $site because $source_dir does not exist" >&2
    return
  fi

  echo "[SYNC] $source_dir -> $SSH_HOST:$target_dir"
  ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" "mkdir -p '$target_dir'"
  rsync -az --delete -e "ssh ${SSH_COMMON_OPTS[*]}" "$source_dir/" "$SSH_USER@$SSH_HOST:$target_dir/"
}

restart_site_man() {
  echo "[REMOTE] Restarting $NODE_DOMAIN via Plesk"
  ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" <<EOF
set -euo pipefail
NODE_DOMAIN="$NODE_DOMAIN"
if command -v plesk >/dev/null 2>&1; then
  plesk bin nodejs --restart "${NODE_DOMAIN}" || true
else
  echo "Plesk CLI not found; skipping restart"
fi
EOF
}

for site in "${SITES[@]}"; do
  sync_site "$site"
done

restart_site_man

echo "[DONE] Tony sites synced: ${SITES[*]}"
