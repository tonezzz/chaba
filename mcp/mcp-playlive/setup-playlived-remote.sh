#!/bin/bash
# Setup systemd service for playlived on remote tony-dell machine

set -e

REMOTE_HOST="tony-dell.local"
SERVICE_NAME="playlived"
REMOTE_SERVICE_FILE="/tmp/${SERVICE_NAME}.service"
REMOTE_SOURCE_DIR="/home/tony/.local/playlive"
LOCAL_SOURCE_DIR="/home/tony/CascadeProjects/chaba-omen/mcp/mcp-playlive"

echo "Setting up playlived systemd service on ${REMOTE_HOST}..."

# Create service file for remote
cat > "${REMOTE_SERVICE_FILE}" << EOF
[Unit]
Description=Playlive Daemon - Browser Automation Session Manager
After=network.target

[Service]
Type=simple
User=tony
WorkingDirectory=${REMOTE_SOURCE_DIR}
Environment="PATH=/home/tony/.local/node/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/tony/.local/node/bin/node playlived.mjs
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Copy service file to remote machine
scp "${REMOTE_SERVICE_FILE}" "${REMOTE_HOST}:/tmp/"

# Setup service on remote machine
ssh "${REMOTE_HOST}" "sudo bash -c 'cp /tmp/${SERVICE_NAME}.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable ${SERVICE_NAME} && systemctl restart ${SERVICE_NAME} && systemctl status ${SERVICE_NAME}'"

# Cleanup
rm "${REMOTE_SERVICE_FILE}"

echo "playlived service installed and started successfully on ${REMOTE_HOST}"
