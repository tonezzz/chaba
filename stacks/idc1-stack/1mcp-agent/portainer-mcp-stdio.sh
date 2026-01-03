#!/usr/bin/env bash
set -euo pipefail

if [ -z "${PORTAINER_SERVER:-}" ]; then
  echo "PORTAINER_SERVER is required (example: 127.0.0.1:9000)" >&2
  exit 1
fi

if [ -z "${PORTAINER_TOKEN:-}" ]; then
  echo "PORTAINER_TOKEN is required (Portainer admin API token)" >&2
  exit 1
fi

SERVER="${PORTAINER_SERVER}"
if [[ "${SERVER}" != http://* && "${SERVER}" != https://* ]]; then
  SERVER="http://${SERVER}"
fi

TOOLS_PATH="${PORTAINER_TOOLS_PATH:-/tmp/portainer-tools.yaml}"

ARGS=(
  -server "${SERVER}"
  -token "${PORTAINER_TOKEN}"
  -tools "${TOOLS_PATH}"
)

if [ "${PORTAINER_DISABLE_VERSION_CHECK:-0}" = "1" ]; then
  ARGS+=( -disable-version-check )
fi

if [ "${PORTAINER_READ_ONLY:-1}" = "1" ]; then
  ARGS+=( -read-only )
fi

exec /usr/local/bin/portainer-mcp "${ARGS[@]}"
