#!/usr/bin/env bash
# Compatibility shim for the legacy idc02 single-writer-fleet-audit.timer.
# The canonical drift lint is scripts/check-single-writer.sh at the repo root.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$REPO/scripts/check-single-writer.sh" "$@"
