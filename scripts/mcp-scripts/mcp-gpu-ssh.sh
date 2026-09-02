#!/bin/bash
# Run the mcp-gpu server on tony-omen (the GPU host) over SSH.
# The local Devin MCP host passes IMAGEN_URL / LLAMA_URL in the environment;
# we re-export them on the remote side so the server uses the configured endpoints.
set -euo pipefail

IMAGEN_URL="${IMAGEN_URL:-http://tony-omen.taila0626a.ts.net:8080/apps/imagen2/api}"
LLAMA_URL="${LLAMA_URL:-http://tony-omen.taila0626a.ts.net:8001}"

exec /usr/bin/ssh -o BatchMode=yes tony-omen \
  "IMAGEN_URL='${IMAGEN_URL}' LLAMA_URL='${LLAMA_URL}' exec /usr/bin/python3 /home/tony/CascadeProjects/chaba/mcp-servers/mcp-gpu/server.py"
