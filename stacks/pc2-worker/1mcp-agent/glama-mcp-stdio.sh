#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${GLAMA_MCP_VENV_DIR:-/opt/glama-mcp-venv}"
PROJECT_DIR="${GLAMA_MCP_PROJECT_DIR:-/workspaces/chaba/mcp/mcp-glama-stdio}"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "glama-mcp project dir not found: $PROJECT_DIR" >&2
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
fi

"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"

exec "$VENV_DIR/bin/python" "$PROJECT_DIR/server.py"
