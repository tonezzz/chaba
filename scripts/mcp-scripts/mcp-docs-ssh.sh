#!/bin/bash
# mcp-docs-ssh.sh
# Run docs-mcp-server MCP locally
set -euo pipefail

exec /usr/bin/node /home/tony/CascadeProjects/chaba/node_modules/@arabold/docs-mcp-server/dist/index.js mcp \
  --protocol stdio \
  --store-path /home/tony/.local/share/docs-mcp-server \
  --logo false
