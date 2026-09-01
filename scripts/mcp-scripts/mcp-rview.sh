#!/usr/bin/env bash
set -e
# Default to the tony-omen Caddy endpoint. Override with RVIEW_API_URL.
if [ -z "$RVIEW_API_URL" ]; then
  export RVIEW_API_URL="http://tony-dell.taila0626a.ts.net:3007/state"
fi
exec /usr/bin/python3 /home/tony/CascadeProjects/chaba/scripts/mcp_rview/server.py
