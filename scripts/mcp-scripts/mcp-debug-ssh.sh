#!/bin/bash
# mcp-debug-ssh.sh
# Run the mcp-debug stdio server on tony-dell
set -euo pipefail

exec /usr/bin/ssh -o BatchMode=yes tony-dell \
  'cd /home/tony/CascadeProjects/chaba-tony-dell && \
   PYTHONPATH=/home/tony/CascadeProjects/chaba-tony-dell/scripts \
   /usr/bin/python3 -m mcp_debug.server'
