#!/bin/bash
set -e
if [ -z "$LLAMA_URL" ]; then
  if [ -f ~/.config/secrets/llama.env ]; then
    source ~/.config/secrets/llama.env
  fi
fi
if [ -z "$LLAMA_URL" ]; then
  echo "ERROR: LLAMA_URL not set" >&2
  exit 1
fi
exec python3 /home/tony/CascadeProjects/chaba-omen/mcp/mcp-llama/server.py
