#!/usr/bin/env bash
# Pull vault edits made on a remote host (e.g. via apps/obsidian on mn01)
# back into the canonical git checkout on this machine.
#
#   pull-vault.sh [host]     (default: mn01)
#
# After pulling, review + commit locally, then run
# scripts/ada/sync-ada-memory-to-mddb.py to publish to MDDB.

set -euo pipefail
HOST="${1:-mn01}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VAULT="$REPO/docs/ada-memory"
REMOTE="$HOST:CascadeProjects/chaba-vault/docs/ada-memory/"

rsync -avz "$REMOTE" "$VAULT/"
echo "pulled $REMOTE -> $VAULT"
git -C "$REPO" status --short docs/ada-memory || true
