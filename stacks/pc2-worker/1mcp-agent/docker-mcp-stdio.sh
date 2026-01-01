#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${DOCKER_MCP_VENV_DIR:-/opt/docker-mcp-venv}"
PROJECT_DIR="${DOCKER_MCP_PROJECT_DIR:-/workspaces/chaba/mcp/mcp-docker}"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "docker-mcp project dir not found: $PROJECT_DIR" >&2
  exit 1
fi

ensure_venv() {
  mkdir -p "$VENV_DIR"
  find "$VENV_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  python3 -m venv "$VENV_DIR"
  ln -sf "$VENV_DIR/bin/python" "$VENV_DIR/bin/python3"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
}

if [ ! -x "$VENV_DIR/bin/python" ] || [ ! -x "$VENV_DIR/bin/python3" ]; then
  ensure_venv
else
  # Even if the files exist, the interpreter symlink can point at a deleted
  # system python after base image changes. Validate by executing it.
  if ! "$VENV_DIR/bin/python3" --version >/dev/null 2>&1; then
    ensure_venv
  fi
fi

"$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR"

exec "$VENV_DIR/bin/docker-mcp"
