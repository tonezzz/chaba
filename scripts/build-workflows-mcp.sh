#!/bin/bash
# Build the workflows-mcp Podman image.
# Run this on tony-dell (or the Podman host that will run the container).
set -euo pipefail

cd "$(dirname "$0")/.."
podman build -f stacks/podman/Containerfile.workflows-mcp -t localhost/workflows-mcp:latest .

echo "Built localhost/workflows-mcp:latest"
echo "Restart the container with: systemctl --user restart workflows-mcp.service"
