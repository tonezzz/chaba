#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}
CODE_SERVER_CONTAINER=${CODE_SERVER_CONTAINER:-idc1-code-server}
WORKSPACE_PATH=${WORKSPACE_PATH:-/workspaces/chaba}

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

echo "[IDC1] Listing ${WORKSPACE_PATH} inside ${CODE_SERVER_CONTAINER}"

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" <<EOF
set -euo pipefail
echo "[REMOTE] Host: \$(hostname)"
docker exec ${CODE_SERVER_CONTAINER@Q} ls -al ${WORKSPACE_PATH@Q}
EOF

echo "[IDC1] Workspace listing complete."
