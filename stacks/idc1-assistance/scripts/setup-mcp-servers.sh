#!/bin/sh
set -e

echo "Setting up MCP servers..."

# Core setup
/app/scripts/01-setup-directories.sh
/app/scripts/02-setup-config.sh
/app/scripts/03-setup-google-tasks.sh
/app/scripts/04-setup-google-sheets.sh
/app/scripts/05-setup-google-calendar.sh
/app/scripts/06-setup-http-patching.sh
/app/scripts/07-setup-proxy.sh

echo "MCP servers setup completed"
