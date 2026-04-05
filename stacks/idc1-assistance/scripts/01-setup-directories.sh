#!/bin/sh
set -e

echo "Setting up directories..."

mkdir -p /app/mcp-config
mkdir -p /app/mcp-servers/mcp-google-tasks
mkdir -p /app/mcp-servers/mcp-google-sheets
mkdir -p /app/mcp-servers/mcp-google-calendar
mkdir -p /root/.config/1mcp

echo "Directories setup completed"
