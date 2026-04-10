#!/bin/bash
# Load GhostRoute discovery config into environment
# Usage: source load-config.sh [--export]

DISCOVERY_DIR="${GHOSTROUTE_DISCOVERY_DIR:-/workspace/discovery/ghostroute}"
CONFIG_FILE="$DISCOVERY_DIR/latest/recommended_config.json"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Discovery config not found at $CONFIG_FILE" >&2
    echo "Run: python /app/test-ghostroute.py" >&2
    return 1 2>/dev/null || exit 1
fi

# Parse and export
export_autoagent_env() {
    local config="$1"
    # Extract autoagent_env values
    local model=$(echo "$config" | grep -o '"AUTOAGENT_MODEL": "[^"]*"' | cut -d'"' -f4)
    local base_url=$(echo "$config" | grep -o '"AUTOAGENT_API_BASE_URL": "[^"]*"' | cut -d'"' -f4)
    
    [ -n "$model" ] && export AUTOAGENT_MODEL="$model"
    [ -n "$base_url" ] && export AUTOAGENT_API_BASE_URL="$base_url"
    
    echo "Loaded GhostRoute config:"
    echo "  AUTOAGENT_MODEL=$AUTOAGENT_MODEL"
    echo "  AUTOAGENT_API_BASE_URL=$AUTOAGENT_API_BASE_URL"
}

if command -v jq >/dev/null 2>&1; then
    # Use jq if available
    config=$(cat "$CONFIG_FILE" | jq -r '.autoagent_env // {} | to_entries[] | "\(.key)=\(.value)"')
    while IFS='=' read -r key value; do
        [ -n "$key" ] && export "$key=$value"
    done <<< "$config"
    
    echo "Loaded GhostRoute config:"
    echo "  AUTOAGENT_MODEL=$AUTOAGENT_MODEL"
    echo "  AUTOAGENT_API_BASE_URL=$AUTOAGENT_API_BASE_URL"
else
    # Fallback to grep parsing
    config=$(cat "$CONFIG_FILE")
    export_autoagent_env "$config"
fi

# Show fallback chain
if command -v jq >/dev/null 2>&1; then
    echo "  Fallback chain:"
    cat "$CONFIG_FILE" | jq -r '.fallback_chain[]' | while read fallback; do
        echo "    - $fallback"
    done
fi
