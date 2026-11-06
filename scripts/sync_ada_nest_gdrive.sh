#!/usr/bin/env bash
set -euo pipefail

# Copy the Ada Nest tree to the host-side read-only source for ada-opencode.
# This intentionally uses rclone copy, never sync: an absent or incomplete
# remote must not delete the local inspection cache.

RCLONE_BIN="${RCLONE_BIN:-rclone}"
REMOTE_ROOT="${ADA_NEST_GDRIVE_REMOTE:-gdrive:ada-nest-adobe-stock}"
DEST="${ADA_NEST_GDRIVE_DIR:-$HOME/.local/share/ada-opencode/gdrive/ada-nest-adobe-stock}"

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

case "$REMOTE_ROOT" in
    *:ada-nest-adobe-stock) ;;
    *) die "remote must end with :ada-nest-adobe-stock" ;;
esac

command -v "$RCLONE_BIN" >/dev/null 2>&1 ||
    die "rclone is not installed or RCLONE_BIN is invalid"

mkdir -p "$DEST"
"$RCLONE_BIN" copy "$REMOTE_ROOT" "$DEST" --progress "$@"
echo "[OK] copied $REMOTE_ROOT -> $DEST"
