#!/bin/bash
set -e
docker rm -f $(docker ps -aq --filter 'ancestor=ghcr.io/github/github-mcp-server:latest' 2>/dev/null) >/dev/null 2>&1 || true
if [ -f ~/.config/secrets/github-mcp.env ]; then
  set -a
  source ~/.config/secrets/github-mcp.env
  set +a
fi
if [ -z "${GITHUB_ACCESS_TOKEN:-}${GITHUB_PERSONAL_ACCESS_TOKEN:-}" ]; then
  echo "ERROR: GITHUB_ACCESS_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN not set" >&2
  exit 1
fi
export GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:-$GITHUB_ACCESS_TOKEN}"
export GITHUB_TOKEN="${GITHUB_TOKEN:-$GITHUB_PERSONAL_ACCESS_TOKEN}"
exec docker run -i --rm -e GITHUB_ACCESS_TOKEN -e GITHUB_PERSONAL_ACCESS_TOKEN -e GITHUB_TOKEN "ghcr.io/github/github-mcp-server:latest"
