#!/usr/bin/env bash
set -euo pipefail
# Manual build fallback. The Quadlet .build unit normally handles this.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
podman build -f stacks/web/rview-api/Dockerfile -t rview-api:latest .
