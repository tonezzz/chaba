#!/bin/sh
set -e

echo "Setting up Google Tasks server..."

# Copy server file from template
if [ -f /app/templates/servers/google-tasks-server.js ]; then
  cp /app/templates/servers/google-tasks-server.js /app/mcp-servers/mcp-google-tasks/server.js
else
  echo "Warning: Google Tasks server template not found"
fi

chmod +x /app/mcp-servers/mcp-google-tasks/server.js

echo "Google Tasks server setup completed"
