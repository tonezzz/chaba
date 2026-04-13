#!/bin/sh
# Entrypoint for wiki-sync-listener container

export PYTHONUNBUFFERED=1

echo "Installing dependencies..."
pip install --quiet packaging psycopg2-binary 'weaviate-client>=3.26.7,<4.0.0' || {
    echo "❌ Failed to install dependencies"
    exit 1
}

echo "✅ Dependencies installed"
echo "Starting wiki sync listener (interval: ${POLL_INTERVAL:-2.0}s)..."

# Run the listener (Docker restart policy handles failures)
exec python -u /app/scripts/wiki-sync-listener-simple.py --interval "${POLL_INTERVAL:-2.0}"
