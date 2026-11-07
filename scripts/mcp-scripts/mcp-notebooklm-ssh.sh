#!/bin/bash
# Connect to the persistent notebooklm-mcp container on mn01.
set -euo pipefail
exec /usr/bin/ssh -o BatchMode=yes mn01 \
  'podman exec -i notebooklm-mcp notebooklm-mcp --transport stdio'
