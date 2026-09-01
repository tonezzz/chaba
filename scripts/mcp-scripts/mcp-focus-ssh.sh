#!/bin/bash
# mcp-focus-ssh.sh
# Run mcp-focus on tony-dell
set -euo pipefail

exec /usr/bin/ssh -o BatchMode=yes tony-dell \
  'cd /home/tony/CascadeProjects/chaba-tony-dell && \
   PYTHONPATH=/home/tony/CascadeProjects/chaba-tony-dell/scripts \
   /usr/bin/python3 scripts/mcp_focus/server.py'
