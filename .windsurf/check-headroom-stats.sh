#!/bin/bash
# Check Headroom proxy statistics and compression effectiveness
# This script provides real-time monitoring of Headroom proxy performance

echo "Headroom Proxy Statistics"
echo "=========================="
echo ""

# Check if proxy is running
if ! curl -s http://127.0.0.1:8787/health > /dev/null 2>&1; then
    echo "❌ Headroom proxy is not running on port 8787"
    echo "Start it with: .windsurf/start-headroom-proxy.sh"
    exit 1
fi

echo "✅ Headroom proxy is running"
echo ""

# Get basic health info
echo "Basic Health Status:"
echo "==================="
curl -s http://127.0.0.1:8787/health | python3 -m json.tool | head -20
echo ""

# Get detailed statistics
echo "Detailed Statistics:"
echo "==================="
curl -s http://127.0.0.1:8787/stats | python3 -m json.tool
echo ""

# Get compression history if available
echo "Compression History:"
echo "==================="
curl -s http://127.0.0.1:8787/stats-history | python3 -m json.tool 2>/dev/null || echo "No compression history available yet"
echo ""

echo "Key Metrics to Monitor:"
echo "======================"
echo "- Request count: Total number of requests processed"
echo "- Compression ratio: Percentage of tokens saved"
echo "- Cache hit rate: Effectiveness of semantic caching"
echo "- Average latency: Performance impact of compression"
echo ""

echo "For continuous monitoring, run: watch -n 5 '.windsurf/check-headroom-stats.sh'"
