#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${VAJA_MCP_VENV_DIR:-/opt/vaja-mcp-venv}"
PROJECT_DIR="${VAJA_MCP_PROJECT_DIR:-/workspaces/chaba/mcp/mcp-vaja-stdio}"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "vaja-mcp project dir not found: $PROJECT_DIR" >&2
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
fi

"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"

exec "$VENV_DIR/bin/python" "$PROJECT_DIR/server.py"
