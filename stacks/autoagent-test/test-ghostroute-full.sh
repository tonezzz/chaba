#!/bin/bash
# Full GhostRoute Test Workflow
# 
# This script:
# 1. Builds/runs autoagent-test container
# 2. Runs GhostRoute discovery test
# 3. Saves results for other apps to use
#
# Usage: ./test-ghostroute-full.sh

set -e

echo "==================================="
echo "GhostRoute Full Test Workflow"
echo "==================================="

# Check if running from correct directory
if [ ! -f "docker-compose.yml" ]; then
    echo "Error: Must run from stacks/autoagent-test directory"
    exit 1
fi

echo ""
echo "[1/5] Building autoagent-test container..."
docker-compose build --no-cache autoagent

echo ""
echo "[2/5] Starting container..."
docker-compose up -d autoagent

echo ""
echo "[3/5] Waiting for container to be ready..."
sleep 2

echo ""
echo "[4/5] Running GhostRoute discovery test..."
docker exec -it autoagent-test bash -c "
    cd /app && 
    python test-ghostroute.py
"

echo ""
echo "[5/5] Verifying discovery files..."
docker exec autoagent-test ls -la /workspace/discovery/ghostroute/latest/

echo ""
echo "==================================="
echo "Test Complete!"
echo "==================================="
echo ""
echo "Discovery files available at:"
echo "  - docker: /workspace/discovery/ghostroute/latest/"
echo "  - host:   ./discovery/ghostroute/latest/ (via volume)"
echo ""
echo "To query results:"
echo "  docker exec autoagent-test python /app/mcp-query.py best"
echo "  docker exec autoagent-test python /app/mcp-query.py fallbacks"
echo "  docker exec autoagent-test python /app/mcp-query.py config"
echo ""
echo "To use in other stacks, mount the discovery:"
echo "  volumes:"
echo "    - autoagent-discovery:/discovery/ghostroute:ro"
echo ""
