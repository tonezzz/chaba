#!/usr/bin/env bash
# Query tony-omen mcp-health critical services and cache the result on tony-dell.
# Runs less frequently than tony-dell-monitor.sh because it spawns the full mcp-health server.

set -uo pipefail

LOG_DIR="$HOME/var/chaba/health"
MCP_HEALTH_OUT="$LOG_DIR/tony-dell-mcp-health.json"
TS=$(LC_ALL=C date -u '+%Y-%m-%dT%H:%M:%SZ')

mkdir -p "$LOG_DIR"

TONY_OMEN_IP=$(tailscale ip -4 tony-omen 2>/dev/null || true)
if [[ -z "$TONY_OMEN_IP" ]]; then
    TONY_OMEN_IP="100.75.102.88"
fi

MCP_HEALTH_QUERY="python3 /home/tony/CascadeProjects/chaba/scripts/mcp-health-client.py get_health_score '{\"include_optional\":false}'"
if ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no "tony@${TONY_OMEN_IP}" "$MCP_HEALTH_QUERY" > "${MCP_HEALTH_OUT}.tmp" 2>/dev/null; then
    mv "${MCP_HEALTH_OUT}.tmp" "$MCP_HEALTH_OUT"
    printf '%s\n' "{\"timestamp\":\"$TS\",\"mcp-health\":\"queried\",\"file\":\"$MCP_HEALTH_OUT\"}"
else
    rm -f "${MCP_HEALTH_OUT}.tmp"
    printf '%s\n' "{\"timestamp\":\"$TS\",\"mcp-health\":\"failed\"}" >&2
    exit 1
fi
