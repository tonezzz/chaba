#!/bin/sh
set -e

echo "Setting up HTTP patching..."

MCP_HTTP_JSON_LIMIT="$${ONE_MCP_HTTP_JSON_LIMIT:-5mb}"

# Patch HTTP JSON limit in various locations
find /usr/src/app/node_modules -type f -path '*@modelcontextprotocol*' -path '*/server/express.js' 2>/dev/null | while IFS= read -r f; do
  if [ -z "$$f" ]; then
    continue
  fi
  if [ -f "$$f" ]; then
    sed -i "s/express\.json()/express.json({ limit: process.env.ONE_MCP_HTTP_JSON_LIMIT || \"$${MCP_HTTP_JSON_LIMIT}\" })/g" "$$f" || true
    sed -i "s/express_1\.default\.json()/express_1.default.json({ limit: process.env.ONE_MCP_HTTP_JSON_LIMIT || \"$${MCP_HTTP_JSON_LIMIT}\" })/g" "$$f" || true
  fi
done

sed -i "s/bodyParser\.json()/bodyParser.json({ limit: process.env.ONE_MCP_HTTP_JSON_LIMIT || \"$${MCP_HTTP_JSON_LIMIT}\" })/g" /usr/src/app/transport/http/server.js || true

echo "HTTP patching setup completed"
