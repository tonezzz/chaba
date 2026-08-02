#!/bin/bash
set -e
if [ -z "$GITHUB_PERSONAL_ACCESS_TOKEN" ]; then
  if [ -f ~/.config/secrets/github-mcp.env ]; then
    source ~/.config/secrets/github-mcp.env
  fi
fi
if [ -z "$GITHUB_PERSONAL_ACCESS_TOKEN" ]; then
  echo "ERROR: GITHUB_PERSONAL_ACCESS_TOKEN not set" >&2
  exit 1
fi
exec docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN "ghcr.io/github/github-mcp-server:latest"
