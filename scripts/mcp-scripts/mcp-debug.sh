#!/usr/bin/env bash

REPO=/home/tony/CascadeProjects/chaba
PIDFILE="${XDG_RUNTIME_DIR:-/run/user/$(id - u)}/mcp-debug.pid"

# Reuse a healthy existing mcp_debug server instead of killing it.
if [ -f "$PIDFILE" ]; then
  old=$(cat "$PIDFILE" 2>/dev/null)
  if [ -n "$old" ] && [ "$old" != "$$" ] && kill -0 "$old" 2>/dev/null; then
    # existing server is alive; let the client reuse it
    exit 0
  fi
  rm -f "$PIDFILE"
fi

# Only kill a stale supervisor, not a running server we may still be using.
pkill -9 -f 'mcp_debug\.supervisor' 2>/dev/null || true
sleep 0.2

cd "$REPO"
export PYTHONPATH="$REPO/scripts${PYTHONPATH:+:$PYTHONPATH}"

echo $$ > "$PIDFILE"
exec /home/tony/CascadeProjects/chaba/venv/bin/python -m mcp_debug.server
