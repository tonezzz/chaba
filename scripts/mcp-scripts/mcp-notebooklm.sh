#!/bin/bash
# notebooklm-mcp lives only on mn01 (moved off tony-dell 2026-10-26);
# the "local" name is kept for config compatibility — it ssh-execs to mn01.
set -euo pipefail
exec /usr/bin/ssh -o BatchMode=yes mn01 \
  'podman exec -i notebooklm-mcp notebooklm-mcp --transport stdio'
