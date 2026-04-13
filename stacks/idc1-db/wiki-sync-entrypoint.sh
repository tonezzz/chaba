#!/bin/sh
# Entrypoint for wiki-sync-listener container

echo "Installing dependencies..."
pip install --quiet packaging psycopg2-binary 'weaviate-client>=3.26.7,<4.0.0' google-genai python-dotenv || {
    echo "❌ Failed to install dependencies"
    sleep 10
    exit 1
}

echo "✅ Dependencies installed"
echo "Starting wiki sync listener (interval: ${POLL_INTERVAL:-1.0}s)..."

# Run the listener - restart on failure
while true; do
    PYTHONUNBUFFERED=1 python -u /app/scripts/wiki-sync-listener-simple.py --interval "${POLL_INTERVAL:-1.0}"
    EXIT_CODE=$?
    echo "⚠️ Listener exited with code $EXIT_CODE, restarting in 5s..."
    sleep 5
done
