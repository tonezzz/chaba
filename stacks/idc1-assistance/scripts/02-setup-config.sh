#!/bin/sh
set -e

echo "Setting up MCP configuration..."

# Generate config from template if it exists
if [ -f /app/templates/mcp-config.template.json ]; then
  envsubst < /app/templates/mcp-config.template.json > /app/mcp-config/mcp.json
else
  # Create default config
  cat > /app/mcp-config/mcp.json <<'EOF'
{
  "$schema": "https://docs.1mcp.app/schemas/v1.0.0/mcp-config.json",
  "mcpServers": {
    "fetch": {
      "command": "/opt/venv/bin/python",
      "args": ["-m", "mcp_server_fetch"],
      "tags": ["fetch", "web"],
      "disabled": false
    },
    "server-sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
      "tags": ["thinking"],
      "disabled": false
    },
    "google-tasks": {
      "command": "node",
      "args": ["/app/mcp-servers/mcp-google-tasks/server.js"],
      "env": {
        "GOOGLE_TASKS_TOKEN_PATH": "${GOOGLE_SHARED_TOKEN_PATH:-/root/.config/1mcp/google.tokens.json}"
      },
      "tags": ["google", "tasks"],
      "disabled": false
    },
    "google-sheets": {
      "command": "node",
      "args": ["/app/mcp-servers/mcp-google-sheets/server.js"],
      "env": {
        "GOOGLE_SHEETS_TOKEN_PATH": "${GOOGLE_SHARED_TOKEN_PATH:-/root/.config/1mcp/google.tokens.json}"
      },
      "tags": ["google", "sheets"],
      "disabled": false
    },
    "google-calendar": {
      "command": "node",
      "args": ["/app/mcp-servers/mcp-google-calendar/server.js"],
      "env": {
        "GOOGLE_CALENDAR_TOKEN_PATH": "${GOOGLE_SHARED_TOKEN_PATH:-/root/.config/1mcp/google.tokens.json}"
      },
      "tags": ["google", "calendar"],
      "disabled": false
    }
  }
}
EOF
fi

# Create symlink for 1mcp
ln -sf /app/mcp-config/mcp.json /root/.config/1mcp/mcp.json

echo "MCP configuration setup completed"
