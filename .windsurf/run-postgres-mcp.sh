#!/bin/bash
set -e
source /home/tony/.config/secrets/postgres-mcp.env
exec npx -y @modelcontextprotocol/server-postgres "$DATABASE_URL"
