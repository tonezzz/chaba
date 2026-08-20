#!/usr/bin/env bash
set -euo pipefail
# Build the rview-api image from the repo root so the Containerfile can copy
# stacks/web/rview-api/rview-api.mjs.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
podman build -f stacks/tony-dell/rview-api/Containerfile -t rview-api:latest .
