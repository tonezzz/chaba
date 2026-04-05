#!/bin/sh
set -e

echo "Setting up Google Sheets server..."

# Create a placeholder for Google Sheets server (would be extracted similarly)
cat > /app/mcp-servers/mcp-google-sheets/server.js <<'EOF'
"use strict";

const APP_NAME = "mcp-google-sheets";
const APP_VERSION = "0.0.1";

// Google Sheets server implementation would go here
// For now, this is a placeholder

console.log("Google Sheets server started");
EOF

chmod +x /app/mcp-servers/mcp-google-sheets/server.js

echo "Google Sheets server setup completed"
