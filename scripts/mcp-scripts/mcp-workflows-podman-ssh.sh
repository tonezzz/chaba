#!/bin/bash
# Connect to the persistent workflows-mcp container on tony-dell.
set -euo pipefail
exec /usr/bin/ssh -o BatchMode=yes tony-dell \
  'podman exec -i workflows-mcp workflows-mcp'
