#!/usr/bin/env bash
# Single-instance launcher for stdio MCP servers.
# Usage: mcp-single-instance.sh <pattern> <command> [args...]
# <pattern> is a pgrep-safe substring that uniquely identifies this MCP server
# (e.g. "mcp-gpu/server.py" or "enhanced-postgres-mcp").
set -euo pipefail

pattern="$1"
shift

# Find existing instances matching the pattern, excluding this shell.
# Keep the newest (highest PID) and kill the rest.
to_kill=$(pgrep -f "$pattern" | grep -v "$$" | sort -n | head -n -1)
if [ -n "$to_kill" ]; then
  echo "[mcp-single-instance] $pattern: killing old PIDs $to_kill" >&2
  # shellcheck disable=SC2086
  kill -15 $to_kill 2>/dev/null || true
  sleep 1
  # Force any stragglers
  # shellcheck disable=SC2086
  kill -9 $to_kill 2>/dev/null || true
fi

exec "$@"
