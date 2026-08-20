#!/usr/bin/env bash
set -euo pipefail
# Build the gemini-live image from the repo root.  The Containerfile installs
# Python 3, copies the server and package manifest, and copies scripts/mcp_rview
# to /scripts/mcp_rview where server.mjs expects it.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
podman build -f stacks/tony-dell/gemini-live/Containerfile -t gemini-live:latest .
