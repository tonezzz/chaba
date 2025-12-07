#!/usr/bin/env bash
set -euo pipefail

# Wrapper for mirroring the a1-idc1 site onto dev-host.pc1
# Uses the same deploy-node-1 pipeline with dev-host defaults.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export SSH_USER="${SSH_USER:-tonezzz}"
export SSH_HOST="${SSH_HOST:-dev-host.pc1}"
export SSH_PORT="${SSH_PORT:-22}"
export SSH_KEY_PATH="${SSH_KEY_PATH:-/home/tonezzz/.ssh/chaba_ed25519}"
export REMOTE_BASE="${REMOTE_BASE:-/var/www/a1}"
export LOCAL_BASE="${LOCAL_BASE:-sites}"
export ENV_DIR="${ENV_DIR:-$REPO_ROOT/.secrets/dev-host}"
export APPS="${APPS:-a1-idc1}"
export RELEASES_TO_KEEP="${RELEASES_TO_KEEP:-10}"

exec "$REPO_ROOT/scripts/deploy-node-1.sh"
