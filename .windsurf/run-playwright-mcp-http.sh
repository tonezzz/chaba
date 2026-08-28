#!/bin/bash
set -e
PORT="${PLAYWRIGHT_MCP_PORT:-8931}"
echo "Starting Playwright MCP HTTP server on port $PORT..." >&2
exec npx -y @playwright/mcp@0.0.78 --port "$PORT"
