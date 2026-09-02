#!/bin/bash
# Yomi MCP launcher wrapper.
# Applies the local long-poll timeout patch required for LINE passwordless
# login, then execs the Yomi MCP server. This wrapper lets the patch survive
# Yomi package reinstalls until the upstream fix lands.
set -euo pipefail

YOMI_PWLESS_FILE="/home/tony/.yomi/mcpb/dist/line/auth/pwless/index.js"

if [ -f "$YOMI_PWLESS_FILE" ]; then
    # Increase the long-poll timeout so the server holds the connection
    # long enough for the user to enter the PIN and approve the device.
    sed -i \
        -e "s/'x-lst': '60000'/'x-lst': '180000'/g" \
        -e "s/pollTimeout: PWLESS_POLL_TIMEOUT_MS,/pollTimeout: 185000,/g" \
        "$YOMI_PWLESS_FILE"
fi

exec node /home/tony/.yomi/mcpb/run.mjs
