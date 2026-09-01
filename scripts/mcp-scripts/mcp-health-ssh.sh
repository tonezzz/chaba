#!/bin/bash
# mcp-health-ssh.sh
# Run mcp-health on tony-dell
set -euo pipefail

exec /usr/bin/ssh -o BatchMode=yes tony-dell \
  'export HEALTH_PROFILE=home; \
   cd /home/tony/CascadeProjects/chaba-tony-dell/mcp-servers/mcp-health && \
   POSTGRES_HOST=localhost \
   POSTGRES_PORT=5432 \
   XDG_RUNTIME_DIR=/run/user/1000 \
   DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
   HEALTH_CONFIG=/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/infrastructure/ssot.health.yml \
   HEALTH_SKILL=/home/tony/CascadeProjects/chaba-tony-dell/.agents/skills/health-check/SKILL.md \
   /usr/bin/node server.js'
