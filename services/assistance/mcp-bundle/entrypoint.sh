#!/bin/sh
set -e

mkdir -p /app/mcp-config
mkdir -p /root/.config/1mcp

if [ ! -f /app/mcp-config/mcp.json ]; then
  echo "missing_mcp_config" >&2
  exit 1
fi

ln -sf /app/mcp-config/mcp.json /root/.config/1mcp/mcp.json

MCP_HTTP_JSON_LIMIT="${ONE_MCP_HTTP_JSON_LIMIT:-5mb}"

# Increase JSON limits in 1mcp HTTP transport (best-effort).
find /usr/src/app/node_modules -type f -path '*@modelcontextprotocol*' -path '*/server/express.js' 2>/dev/null | while IFS= read -r f; do
  if [ -z "$f" ]; then
    continue
  fi
  if [ -f "$f" ]; then
    sed -i "s/express\.json()/express.json({ limit: process.env.ONE_MCP_HTTP_JSON_LIMIT || \"${MCP_HTTP_JSON_LIMIT}\" })/g" "$f" || true
    sed -i "s/express_1\.default\.json()/express_1.default.json({ limit: process.env.ONE_MCP_HTTP_JSON_LIMIT || \"${MCP_HTTP_JSON_LIMIT}\" })/g" "$f" || true
  fi
done

sed -i "s/bodyParser\.json()/bodyParser.json({ limit: process.env.ONE_MCP_HTTP_JSON_LIMIT || \"${MCP_HTTP_JSON_LIMIT}\" })/g" /usr/src/app/transport/http/server.js 2>/dev/null || true

HOST="${ONE_MCP_HOST:-0.0.0.0}"
PORT="${ONE_MCP_PORT:-${PORT:-3050}}"
EXTERNAL_URL="${ONE_MCP_EXTERNAL_URL:-https://127.0.0.1:${PORT}}"

exec node /usr/src/app/index.js serve \
  --transport http \
  --host "${HOST}" \
  --port "${PORT}" \
  --external-url "${EXTERNAL_URL}" \
  --no-auth \
  --no-enable-auth \
  --enable-async-loading \
  --async-min-servers 0 \
  --async-timeout 5000
