#!/bin/bash
# Start Headroom proxy for token optimization
# This proxy compresses data before it reaches the LLM, reducing token usage by 30-50%

# Configuration
HOST="127.0.0.1"
PORT="8787"
MODE="token"  # Use 'token' for max compression, 'cache' for provider prefix cache stability

# Start the proxy
echo "Starting Headroom proxy on ${HOST}:${PORT} in ${MODE} mode..."
echo "Press Ctrl+C to stop the proxy"

/tmp/headroom-venv/bin/headroom proxy \
  --host "${HOST}" \
  --port "${PORT}" \
  --mode "${MODE}" \
  --no-telemetry
