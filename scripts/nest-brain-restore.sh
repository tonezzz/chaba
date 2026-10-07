#!/usr/bin/env bash
# Restore (hydrate) a Nest brain bundle produced by nest-brain-pack.sh.
#
# Two fetch modes:
#   remote (default): resolve <entity>/<version> under the rclone brain
#       store — --version V, or the `latest` pointer, or newest dir name —
#       then `rclone copy` the version dir to a temp stage.
#   --from-dir DIR:   use an already-staged bundle dir (scp'd tar+manifest).
#       Needs NO rclone — for hosts that have no gdrive remote (mn01).
#
# Verification (never skipped):
#   1. sha256sum -c SHA256SUMS      -> manifest.yml + blobs.tar intact
#   2. manifest entity == requested entity
#   3. epoch fencing: if <dest>/.nest-brain-state exists with epoch >
#      manifest epoch, refuse — that's a stale brain overwriting a newer
#      local respawn generation (--force overrides).
#   4. after extract: sha256sum -c blobs.sha256 per-blob.
#
# Only coreutils/tar/grep are needed for --from-dir restores — yaml is not
# parsed, the few fields are grep'd.
#
# Usage:
#   nest-brain-restore.sh <entity> [--version V|latest] [--dest DIR]
#                         [--from-dir DIR] [--remote R] [--force]
set -euo pipefail

REMOTE="gdrive:nest/brains"
ENTITY=""; VERSION=""; DEST=""; FROMDIR=""; FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2;;
    --dest) DEST="$2"; shift 2;;
    --from-dir) FROMDIR="$2"; shift 2;;
    --remote) REMOTE="${2%/}"; shift 2;;
    --force) FORCE=1; shift;;
    -h|--help) sed -n '2,28p' "$0"; exit 0;;
    *) if [ -z "$ENTITY" ]; then ENTITY="$1"; shift; else echo "unknown arg: $1" >&2; exit 2; fi;;
  esac
done
[ -n "$ENTITY" ] || { echo "usage: nest-brain-restore.sh <entity> [options]" >&2; exit 2; }
DEST="${DEST:-$HOME/.local/share/nest-brains/live/$ENTITY}"

STAGE=""
cleanup() { [ -n "$STAGE" ] && rm -rf "$STAGE"; }
trap cleanup EXIT

if [ -n "$FROMDIR" ]; then
  BUNDLE="$FROMDIR"
else
  if [ -z "$VERSION" ] || [ "$VERSION" = "latest" ]; then
    VERSION=$(rclone cat "$REMOTE/$ENTITY/latest" 2>/dev/null | tr -d '[:space:]' || true)
  fi
  if [ -z "$VERSION" ]; then
    VERSION=$(rclone lsf --dirs-only "$REMOTE/$ENTITY/" 2>/dev/null | sed 's:/$::' | sort -r | head -1)
  fi
  [ -n "$VERSION" ] || { echo "no brain versions found at $REMOTE/$ENTITY/" >&2; exit 1; }
  STAGE=$(mktemp -d /tmp/nest-brain-restore.XXXXXX)
  echo "fetch:    $REMOTE/$ENTITY/$VERSION"
  rclone copy "$REMOTE/$ENTITY/$VERSION" "$STAGE" -q
  BUNDLE="$STAGE"
fi

for f in manifest.yml blobs.tar SHA256SUMS; do
  [ -f "$BUNDLE/$f" ] || { echo "bundle missing $f in $BUNDLE" >&2; exit 1; }
done

# 1+2: integrity + entity match
(cd "$BUNDLE" && sha256sum -c SHA256SUMS >/dev/null) \
  || { echo "SHA256SUMS check FAILED — bundle corrupt/tampered" >&2; exit 1; }
M_ENTITY=$(sed -n 's/^entity:[[:space:]]*//p' "$BUNDLE/manifest.yml" | head -1 | tr -d "\"' ")
M_VERSION=$(sed -n 's/^version:[[:space:]]*//p' "$BUNDLE/manifest.yml" | head -1 | tr -d "\"' ")
M_EPOCH=$(sed -n 's/^epoch:[[:space:]]*//p' "$BUNDLE/manifest.yml" | head -1)
M_EPOCH=${M_EPOCH:-0}
[ "$M_ENTITY" = "$ENTITY" ] || { echo "manifest entity '$M_ENTITY' != requested '$ENTITY'" >&2; exit 1; }

# 3: epoch fencing — refuse to hydrate a stale generation over a newer one
if [ -f "$DEST/.nest-brain-state" ]; then
  L_EPOCH=$(sed -n 's/^epoch:[[:space:]]*//p' "$DEST/.nest-brain-state" | head -1)
  L_EPOCH=${L_EPOCH:-0}
  if [ "$L_EPOCH" -gt "$M_EPOCH" ] && [ "$FORCE" = 0 ]; then
    echo "REFUSE: local epoch $L_EPOCH > brain epoch $M_EPOCH at $DEST" >&2
    echo "        (stale brain vs newer local respawn — use --force to override)" >&2
    exit 1
  fi
fi
if [ -d "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ] && [ "$FORCE" = 0 ]; then
  echo "REFUSE: dest $DEST is non-empty (use --force to hydrate over it)" >&2
  exit 1
fi

# 4: hydrate + per-blob verify
mkdir -p "$DEST"
tar -xf "$BUNDLE/blobs.tar" -C "$DEST"
(cd "$DEST" && sha256sum -c blobs.sha256 >/dev/null) \
  || { echo "per-blob sha256 check FAILED after extract" >&2; exit 1; }

cat > "$DEST/.nest-brain-state" <<EOF
version: $M_VERSION
epoch: $M_EPOCH
restored_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
on_host: $(hostname)
source: ${FROMDIR:-$REMOTE/$ENTITY/$M_VERSION}
EOF

echo "== nest-brain-restore =="
echo "entity:   $M_ENTITY   epoch: $M_EPOCH"
echo "version:  $M_VERSION"
echo "dest:     $DEST ($(find "$DEST" -type f | wc -l) files)"
grep -A4 '^bench:' "$BUNDLE/manifest.yml" | sed 's/^/  /' || true
grep -A3 '^resume:' "$BUNDLE/manifest.yml" | sed 's/^/  /' || true
echo "verify:   OK — SHA256SUMS + per-blob shas match"
