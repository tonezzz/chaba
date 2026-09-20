#!/usr/bin/env bash
# Pull vault edits made on a remote host (e.g. via apps/obsidian on mn01)
# back into the canonical git checkout on this machine.
#
#   pull-vault.sh [host]     (default: mn01)
#
# After pulling, review + commit locally, then run
# scripts/ada/sync-ada-memory-to-mddb.py to publish to MDDB.

set -euo pipefail
HOST="mn01"
COMMIT=0
for arg in "$@"; do
  case "$arg" in
    --commit) COMMIT=1 ;;
    *) HOST="$arg" ;;
  esac
done
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VAULT="$REPO/docs/ada-memory"
REMOTE="$HOST:CascadeProjects/chaba-vault/docs/ada-memory/"

rsync -avz "$REMOTE" "$VAULT/"
echo "pulled $REMOTE -> $VAULT"

if [[ "$COMMIT" == 1 ]]; then
  # personal/* is gitignored — only curated/public notes are committed.
  git -C "$REPO" add docs/ada-memory
  if ! git -C "$REPO" diff --cached --quiet; then
    git -C "$REPO" commit -qm "vault(ada-memory): pull mn01 edits $(date +%F)"
    git -C "$REPO" push -q origin HEAD
    echo "committed + pushed vault changes"
  else
    echo "no vault changes to commit"
  fi
else
  git -C "$REPO" status --short docs/ada-memory || true
fi
