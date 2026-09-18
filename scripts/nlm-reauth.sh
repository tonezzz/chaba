#!/usr/bin/env bash
# Re-authenticate NotebookLM (nlm) and sync credentials to the container host.
#
# The MCP tools on tony-dell's notebooklm-mcp container read auth from
#   ~/.local/share/notebooklm/.notebooklm-mcp-cli/profiles/default/
# Browser login can only happen on a host with a display + Chrome (tony-omen).
#
# Usage: scripts/nlm-reauth.sh [auth-host]   (default: tony-dell)
#   1. Runs the real nlm binary locally -> opens Chrome for Google sign-in
#   2. scp's fresh cookies.json/metadata.json to the container's auth dir
#   3. Verifies with `nlm login --check` inside the container
#
# Env:
#   NLM_BIN       path to real nlm (default: ~/.local/share/nlm-venv/bin/nlm)
#   NLM_PROFILE   profile name (default: default)
#   SKIP_BROWSER  if set, skip login and only sync+verify existing creds

set -euo pipefail

AUTH_HOST="${1:-tony-dell}"
NLM_BIN="${NLM_BIN:-$HOME/.local/share/nlm-venv/bin/nlm}"
NLM_PROFILE="${NLM_PROFILE:-default}"
LOCAL_DIR="$HOME/.notebooklm-mcp-cli/profiles/$NLM_PROFILE"
REMOTE_DIR=".local/share/notebooklm/.notebooklm-mcp-cli/profiles/$NLM_PROFILE"

if [[ ! -x "$NLM_BIN" ]]; then
    echo "error: nlm binary not found at $NLM_BIN" >&2
    echo "hint: ~/.local/bin/nlm is an ssh wrapper (NLM_HOST), not the real binary" >&2
    exit 1
fi

if [[ -z "${SKIP_BROWSER:-}" ]]; then
    echo ">>> Launching browser for Google sign-in on this machine..."
    "$NLM_BIN" login
else
    echo ">>> SKIP_BROWSER set, using existing credentials in $LOCAL_DIR"
fi

for f in cookies.json metadata.json; do
    [[ -f "$LOCAL_DIR/$f" ]] || { echo "error: $LOCAL_DIR/$f missing after login" >&2; exit 1; }
done

echo ">>> Syncing credentials to $AUTH_HOST:$REMOTE_DIR"
ssh -o BatchMode=yes "$AUTH_HOST" "mkdir -p $REMOTE_DIR"
scp -o BatchMode=yes "$LOCAL_DIR/cookies.json" "$LOCAL_DIR/metadata.json" "$AUTH_HOST:$REMOTE_DIR/"

echo ">>> Verifying inside notebooklm-mcp container on $AUTH_HOST"
ssh -o BatchMode=yes "$AUTH_HOST" 'podman exec -i notebooklm-mcp nlm login --check'
