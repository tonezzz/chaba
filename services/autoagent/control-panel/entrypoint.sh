#!/bin/bash
set -e

# Copy research scripts to workspace (volume mounts shadow build-time copies)
# Always sync to ensure updates from new images are applied
echo "📁 Syncing research scripts to workspace..."
cp /app/free-research.py /workspace/ 2>/dev/null || true
cp /app/smart-research.py /workspace/ 2>/dev/null || true
cp /app/wiki-knowledge.py /workspace/ 2>/dev/null || true
cp /app/postgres_kb.py /workspace/ 2>/dev/null || true
echo "✅ Research scripts synced to workspace"

# Start control server automatically in background
if [ -f /app/control-server.py ]; then
    echo "🚀 Starting AutoAgent Control Server..."
    cd /app && python control-server.py --port 8080 &
    sleep 2
    echo "✅ Control Server available at http://localhost:8059/"
    echo "✅ Runner Panel available at http://localhost:8059/runner"
    echo ""
fi

# Function to check if container is running interactively
if [ -t 0 ]; then
    echo "🤖 AutoAgent Test Container"
    echo "================================"
    echo ""
    echo "Available commands:"
    echo "  auto main              - Start full AutoAgent (user mode, agent editor, workflow editor)"
    echo "  auto deep-research     - Start deep research mode only"
    echo "  auto agent --help      - Show agent command options"
    echo "  auto workflow --help   - Show workflow command options"
    echo ""
    echo "Environment variables:"
    echo "  COMPLETION_MODEL: $COMPLETION_MODEL"
    echo "  DEBUG: $DEBUG"
    echo "  API_BASE_URL: $API_BASE_URL"
    echo ""
    echo "Workspace directory: /workspace"
    echo ""
    
    # Check if API keys are configured
    if [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$GEMINI_API_KEY" ]; then
        echo "⚠️  WARNING: No LLM API keys detected!"
        echo "Please configure at least one of the following in .env:"
        echo "  OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY"
        echo ""
    fi
    
    # Start bash shell for interactive use
    exec /bin/bash
else
    echo "AutoAgent running in non-interactive mode"
    echo "Use docker exec -it autoagent-test bash to enter container"
    # Keep container running
    tail -f /dev/null
fi
