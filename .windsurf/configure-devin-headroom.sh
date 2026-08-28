#!/bin/bash
# Configure Devin Desktop to use Headroom proxy for token optimization
# This script sets up the environment variables and configuration needed

echo "Configuring Devin Desktop to use Headroom proxy..."
echo "Headroom proxy should be running on http://127.0.0.1:8787"
echo ""

# Check if Headroom proxy is running
if ! curl -s http://127.0.0.1:8787/health > /dev/null 2>&1; then
    echo "❌ Headroom proxy is not running on port 8787"
    echo "Start it first with: .windsurf/start-headroom-proxy.sh"
    exit 1
fi

echo "✅ Headroom proxy is running"
echo ""

# Method 1: Environment variable configuration
echo "Method 1: Environment Variable Configuration"
echo "============================================"
echo "Add this to your shell profile (~/.bashrc or ~/.zshrc):"
echo ""
echo "export ANTHROPIC_BASE_URL=http://127.0.0.1:8787"
echo ""
echo "Then reload your shell: source ~/.bashrc"
echo ""

# Method 2: Devin Desktop configuration (if supported)
echo "Method 2: Devin Desktop Configuration"
echo "===================================="
echo "If Devin Desktop supports custom API endpoints:"
echo "1. Open Devin Desktop Settings"
echo "2. Navigate to API Configuration"
echo "3. Set Base URL to: http://127.0.0.1:8787"
echo "4. Save and restart Devin Desktop"
echo ""

# Method 3: Session-specific configuration
echo "Method 3: Session-Specific Configuration"
echo "========================================"
echo "For a single session, run:"
echo ""
echo "ANTHROPIC_BASE_URL=http://127.0.0.1:8787 devin-desktop"
echo ""

# Verification
echo "Verification"
echo "============"
echo "After configuration, verify proxy is being used:"
echo "1. Check Headroom stats: curl http://127.0.0.1:8787/stats"
echo "2. Look for increased request counts in stats"
echo "3. Monitor compression ratios in stats output"
echo ""

echo "Configuration complete!"
echo "Choose the method that best fits your workflow."
