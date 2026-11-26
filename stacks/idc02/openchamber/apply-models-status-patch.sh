#!/usr/bin/env bash
# apply-models-status-patch.sh — re-apply the OpenChamber models.status
# patch to an installed @openchamber/web package.
#
# The patch adds the 'models.status' control action and the
# /api/openchamber/models/status route (LiteLLM gateway liveness probe).
# It lives in this repo because node_modules is not a source of truth:
# every `npm i -g @openchamber/web` restores pristine files.
# openchamber-update.service runs this via ExecStartPost BEFORE restarting
# openchamber.service; if the patch stops applying (upstream changed the
# context), the update unit FAILS LOUDLY instead of silently dropping
# the feature.
#
# Usage: apply-models-status-patch.sh [PREFIX]
#   PREFIX defaults to $HOME/.local/node (the openchamber install prefix).
#
# Exit: 0 = patch present (applied now or already there); 1 = could not
# apply — requires regenerating the patch for the new upstream version.
set -euo pipefail

PREFIX="${1:-$HOME/.local/node}"
PKG="$PREFIX/lib/node_modules/@openchamber/web"
PATCH_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/openchamber-models-status.patch"
MARKER="models.status"
MARKER_FILE="$PKG/build/server/lib/openchamber-control/actions.js"

PATCHED_FILES=(
  build/server/runtime.js
  build/server/lib/server-frame/bootstrap-runtime.js
  build/server/lib/openchamber-control/service.js
  build/server/lib/openchamber-control/actions.js
  build/server/lib/self-update/openchamber-routes.js
)

[ -d "$PKG" ] || { echo "ERROR: package not found at $PKG" >&2; exit 1; }
[ -f "$PATCH_FILE" ] || { echo "ERROR: patch file missing: $PATCH_FILE" >&2; exit 1; }

if grep -q "$MARKER" "$MARKER_FILE" 2>/dev/null; then
  echo "models.status patch already applied in $PKG — nothing to do"
  exit 0
fi

echo "applying $PATCH_FILE to $PKG"
if ! patch --dry-run -p1 -d "$PKG" < "$PATCH_FILE" > /dev/null; then
  echo "ERROR: patch does not apply cleanly — upstream @openchamber/web changed." >&2
  echo "Regenerate stacks/idc02/openchamber/openchamber-models-status.patch" >&2
  echo "against the new version (see card ocb-models-status-patch-durability)." >&2
  exit 1
fi
patch -p1 -d "$PKG" < "$PATCH_FILE" > /dev/null

NODE="$HOME/.local/node24/bin/node"
[ -x "$NODE" ] || NODE="$(command -v node || true)"
if [ -n "$NODE" ]; then
  for f in "${PATCHED_FILES[@]}"; do
    "$NODE" --check "$PKG/$f" > /dev/null
  done
fi

echo "models.status patch applied and syntax-checked in $PKG"
