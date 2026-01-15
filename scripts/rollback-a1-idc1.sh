#!/usr/bin/env bash
set -euo pipefail

# Wrapper for rolling the a1-idc1 site back to a specific release.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export SSH_USER="${SSH_USER:-chaba}"
export SSH_HOST="${SSH_HOST:-a1.idc1.surf-thailand.com}"
export SSH_PORT="${SSH_PORT:-22}"
export SSH_KEY_PATH="${SSH_KEY_PATH:-$REPO_ROOT/.secrets/dev-host/.ssh/chaba_ed25519}"
export REMOTE_BASE="${REMOTE_BASE:-/www/a1.idc1.surf-thailand.com}"
export APP="${APP:-a1-idc1}"

exec "$REPO_ROOT/scripts/rollback-node-1.sh"
