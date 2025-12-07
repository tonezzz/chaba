#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODE_SCRIPT="$SCRIPT_DIR/diagnostics-dev-host.mjs"

if ! command -v node >/dev/null 2>&1; then
  echo "[diagnostics-dev-host] node is not available in PATH" >&2
  exit 1
fi

exec node "$NODE_SCRIPT"
