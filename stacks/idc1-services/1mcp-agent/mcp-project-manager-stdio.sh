#!/usr/bin/env bash
set -euo pipefail

: "${MCP_TASK_DATA_DIR:=/data/mcp-project-manager}"
mkdir -p "${MCP_TASK_DATA_DIR}"

exec npx -y mcp-project-manager
