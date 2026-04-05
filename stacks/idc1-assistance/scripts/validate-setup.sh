#!/bin/sh
set -e

echo "Validating MCP setup..."

# Check required environment variables
required_vars="GOOGLE_CLIENT_ID ONE_MCP_HOST ONE_MCP_PORT"
for var in $required_vars; do
  if [ -z "$(eval echo \$$var)" ]; then
    echo "WARNING: Environment variable $var is not set"
  fi
done

# Validate config files
test -f /app/mcp-config/mcp.json || {
  echo "ERROR: MCP config file not found"
  exit 1
}

# Validate server files
test -f /app/mcp-servers/mcp-google-tasks/server.js || {
  echo "ERROR: Google Tasks server file not found"
  exit 1
}

echo "Validation passed"
