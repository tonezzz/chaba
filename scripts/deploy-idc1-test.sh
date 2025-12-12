#!/usr/bin/env bash
set -euo pipefail

# Wrapper to deploy the test.idc1 site to the idc1 host (same machine as a1.idc1).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PUBLIC_DIR="$REPO_ROOT/sites/idc1/public"
if [[ ! -f "$PUBLIC_DIR/index.html" ]]; then
  echo "[ERROR] Missing $PUBLIC_DIR/index.html" >&2
  exit 2
fi

STAGING_DIR="$(mktemp -d -t idc1-test-deploy-XXXXXXXX)"
cleanup() {
  rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

mkdir -p "$STAGING_DIR/test"
rsync -az --delete "$PUBLIC_DIR/" "$STAGING_DIR/test/"

export SSH_USER="${SSH_USER:-chaba}"
export SSH_HOST="${SSH_HOST:-idc1.surf-thailand.com}"
export SSH_PORT="${SSH_PORT:-22}"
export SSH_KEY_PATH="${SSH_KEY_PATH:-${HOME:-/home/chaba}/.ssh/chaba_ed25519}"
export REMOTE_BASE="${REMOTE_BASE:-/www/idc1.surf-thailand.com}"
export LOCAL_BASE="${LOCAL_BASE:-$STAGING_DIR}"
export ENV_DIR="${ENV_DIR:-$REPO_ROOT/.secrets/dev-host}"
export APPS="${APPS:-test}"
export RELEASES_TO_KEEP="${RELEASES_TO_KEEP:-5}"
VERIFY="${VERIFY:-1}"

"$REPO_ROOT/scripts/deploy-node-1.sh"

if [[ "$VERIFY" == "1" ]]; then
  TARGET_URL="${TARGET_URL:-https://test.idc1.surf-thailand.com/test/}" \
    "$REPO_ROOT/scripts/verify-idc1-test.sh"
fi
