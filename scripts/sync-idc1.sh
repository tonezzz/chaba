#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SSH_USER="${SSH_USER:-chaba}"
SSH_HOST="${SSH_HOST:-idc1.surf-thailand.com}"
SSH_PORT="${SSH_PORT:-22}"
SSH_KEY_PATH="${SSH_KEY_PATH:-${HOME}/.ssh/chaba_ed25519}"
REMOTE_PATH="${REMOTE_PATH:-/home/chaba/chaba}"

EXCLUDES=(
  --exclude '.git'
  --exclude '.venv'
  --exclude '.secrets'
)

echo "[sync-idc1] Syncing ${REPO_ROOT} → ${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}"
rsync -az --delete "${EXCLUDES[@]}" \
  -e "ssh -p ${SSH_PORT} -i ${SSH_KEY_PATH} -o StrictHostKeyChecking=no" \
  "${REPO_ROOT}/" "${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}/"

echo "[sync-idc1] Sync complete."
