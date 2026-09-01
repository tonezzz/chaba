#!/bin/bash
set -e
if [ -f ~/.config/secrets/postgres-mcp.env ]; then
  set -a
  source ~/.config/secrets/postgres-mcp.env
  set +a
fi
if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL not set" >&2
  exit 1
fi
export POSTGRES_CONNECTION_STRING="$DATABASE_URL"
echo "DEBUG: POSTGRES_CONNECTION_STRING=$POSTGRES_CONNECTION_STRING" >&2
exec /usr/bin/node /home/tony/.local/mcp-postgres-itunified/node_modules/@itunified.io/mcp-postgres/dist/index.js
