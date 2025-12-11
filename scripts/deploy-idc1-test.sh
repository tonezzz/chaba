#!/usr/bin/env bash
set -euo pipefail

# Wrapper to deploy the test.idc1 site to the idc1 host (same machine as a1.idc1).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export SSH_USER="${SSH_USER:-chaba}"
export SSH_HOST="${SSH_HOST:-idc1.surf-thailand.com}"
export SSH_PORT="${SSH_PORT:-22}"
export SSH_KEY_PATH="${SSH_KEY_PATH:-$REPO_ROOT/.secrets/dev-host/.ssh/chaba_ed25519}"
export REMOTE_BASE="${REMOTE_BASE:-/www/idc1.surf-thailand.com}"
export LOCAL_BASE="${LOCAL_BASE:-sites/idc1}"
export ENV_DIR="${ENV_DIR:-$REPO_ROOT/.secrets/dev-host}"
export APPS="${APPS:-test}"
export RELEASES_TO_KEEP="${RELEASES_TO_KEEP:-5}"

exec "$REPO_ROOT/scripts/deploy-node-1.sh"
