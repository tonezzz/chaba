#!/usr/bin/env bash
set -euo pipefail
# Manual build fallback. The Quadlet .build unit normally handles this.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
podman build --build-arg GEMINI_LIVE_PORT=3008 -f stacks/web/gemini-live/Dockerfile -t gemini-live:latest .
