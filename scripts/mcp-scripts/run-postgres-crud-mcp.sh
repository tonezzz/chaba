#!/bin/bash
set -e
source /home/tony/.config/secrets/postgres-mcp.env
exec /home/tony/.local/postgres-mcp/node_modules/.bin/enhanced-postgres-mcp "$DATABASE_URL"
