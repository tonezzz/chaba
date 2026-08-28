#!/bin/bash
#
# Monitoring Dashboard Test Script
# Tests the monitoring dashboard functionality
#

set -eo pipefail

echo "Testing Chaba Monitoring Dashboard..."

# Test 1: Check if script exists and is executable
if [ ! -x "/home/tony/CascadeProjects/chaba/scripts/monitoring-dashboard.mjs" ]; then
    echo "❌ Dashboard script not found or not executable"
    exit 1
fi
echo "✅ Dashboard script exists and is executable"

# Test 2: Check if Node.js is available
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found"
    exit 1
fi
echo "✅ Node.js is available"

# Test 3: Check systemd service file
if [ ! -f "/home/tony/CascadeProjects/chaba/systemd/chaba-monitoring-dashboard.service" ]; then
    echo "❌ Systemd service file not found"
    exit 1
fi
echo "✅ Systemd service file exists"

# Test 4: Test dashboard startup (background)
echo "Starting dashboard in background on test port..."
# Use a different port for testing to avoid conflicts
TEST_PORT=3003
sed "s/const PORT = 3002/const PORT = $TEST_PORT/" /home/tony/CascadeProjects/chaba/scripts/monitoring-dashboard.mjs > /tmp/test-dashboard.mjs
timeout 5 node /tmp/test-dashboard.mjs &
DASHBOARD_PID=$!
sleep 3

# Test 5: Check if dashboard is accessible
if curl -s http://localhost:$TEST_PORT > /dev/null 2>&1; then
    echo "✅ Dashboard is accessible on port $TEST_PORT"
else
    echo "❌ Dashboard not accessible on port $TEST_PORT"
    kill $DASHBOARD_PID 2>/dev/null || true
    rm -f /tmp/test-dashboard.mjs
    exit 1
fi

# Test 6: Check API endpoint
if curl -s http://localhost:$TEST_PORT/api/status > /dev/null 2>&1; then
    echo "✅ API endpoint is accessible"
else
    echo "❌ API endpoint not accessible"
    kill $DASHBOARD_PID 2>/dev/null || true
    rm -f /tmp/test-dashboard.mjs
    exit 1
fi

# Cleanup
kill $DASHBOARD_PID 2>/dev/null || true
rm -f /tmp/test-dashboard.mjs

echo ""
echo "🎉 All monitoring dashboard tests passed!"
echo "Dashboard is ready to use: http://localhost:3002"