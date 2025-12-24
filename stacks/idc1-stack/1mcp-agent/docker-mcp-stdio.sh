#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${DOCKER_MCP_VENV_DIR:-/opt/docker-mcp-venv}"
PROJECT_DIR="${DOCKER_MCP_PROJECT_DIR:-/workspaces/chaba/mcp/mcp-docker}"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "docker-mcp project dir not found: $PROJECT_DIR" >&2
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
fi

"$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR"

exec "$VENV_DIR/bin/docker-mcp"
