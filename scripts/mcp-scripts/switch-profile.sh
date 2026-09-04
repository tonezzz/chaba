#!/bin/bash
# MCP Profile Switching Script
# Switches between home and mobile network profiles

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHABA_DIR="/home/tony/CascadeProjects/chaba-tony-dell"
GENERATOR="$CHABA_DIR/scripts/generate-mcp-config.py"

# Default to home profile
PROFILE=${1:-home}
CURRENT_IP=${2:-}

# Validate profile
if [[ "$PROFILE" != "home" && "$PROFILE" != "mobile" ]]; then
    echo "ERROR: Invalid profile '$PROFILE'. Use 'home' or 'mobile'."
    exit 1
fi

# For mobile profile, require current IP
if [[ "$PROFILE" == "mobile" && -z "$CURRENT_IP" ]]; then
    echo "ERROR: Mobile profile requires --current-ip argument"
    echo "Usage: $0 mobile --current-ip 192.168.1.100"
    exit 1
fi

echo "Switching to $PROFILE profile..."

# Run the generator with appropriate arguments
if [[ "$PROFILE" == "mobile" ]]; then
    python3 "$GENERATOR" --profile mobile --current-ip "$CURRENT_IP"
else
    python3 "$GENERATOR" --profile home
fi

if [[ $? -eq 0 ]]; then
    echo "✓ Profile switched to $PROFILE"
    echo "Restart Devin Desktop and Windsurf to apply changes"
else
    echo "✗ Profile switch failed"
    exit 1
fi