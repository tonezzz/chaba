#!/bin/bash
# Setup systemd service for playlived on local machine

set -e

SERVICE_NAME="playlived"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SOURCE_DIR="/home/tony/CascadeProjects/chaba-omen/mcp/mcp-playlive"

echo "Setting up playlived systemd service..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "This script must be run as root (use sudo)"
    exit 1
fi

# Copy service file
cp "${SOURCE_DIR}/playlived.service" "${SERVICE_FILE}"

# Reload systemd
systemctl daemon-reload

# Enable and start service
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}

# Check status
systemctl status ${SERVICE_NAME}

echo "playlived service installed and started successfully"
