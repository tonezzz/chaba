#!/usr/bin/env bash
set -euo pipefail

# Configure Google Drive access via rclone for the gaussian-splatting-docker
# workflow. Run this once on the Docker host; containers consume the mounted
# folder through the normal ./data bind mount.

RCLONE_BIN="${RCLONE_BIN:-rclone}"
REMOTE_NAME="${GDRIVE_REMOTE_NAME:-gdrive}"
MOUNT_POINT="${GDRIVE_MOUNT_POINT:-./data/gdrive}"
SYNC_DIR="${GDRIVE_SYNC_DIR:-}"

die() { echo "[ERROR] $*" >&2; exit 1; }
info() { echo "[INFO] $*"; }

command -v "$RCLONE_BIN" >/dev/null 2>&1 || {
    info "rclone not found; installing..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo -n apt-get update && sudo -n apt-get install -y rclone
    elif command -v dnf >/dev/null 2>&1; then
        sudo -n dnf install -y rclone
    elif command -v brew >/dev/null 2>&1; then
        brew install rclone
    else
        curl https://rclone.org/install.sh | sudo -n bash
    fi
}

"$RCLONE_BIN" version >/dev/null || die "rclone is not working"

if ! "$RCLONE_BIN" listremotes | grep -q "^${REMOTE_NAME}:"; then
    info "No rclone remote named '${REMOTE_NAME}' found."
    info "Launching interactive configuration..."
    info "When prompted, choose: n) New remote -> name '${REMOTE_NAME}' -> 'Google Drive' -> follow OAuth steps."
    "$RCLONE_BIN" config
else
    info "Remote '${REMOTE_NAME}' already configured."
fi

"$RCLONE_BIN" listremotes | grep -q "^${REMOTE_NAME}:" || die "Remote '${REMOTE_NAME}' is still not configured."

mkdir -p "$MOUNT_POINT"

if [[ -n "${SYNC_DIR:-}" ]]; then
    info "Syncing Google Drive:${SYNC_DIR} -> ${MOUNT_POINT}"
    "$RCLONE_BIN" sync "${REMOTE_NAME}:${SYNC_DIR}" "$MOUNT_POINT" --progress
    info "Sync complete. Data is available at ${MOUNT_POINT}"
    exit 0
fi

# Live mount path
if [[ -f /etc/fuse.conf ]] && ! grep -q "^user_allow_other" /etc/fuse.conf; then
    info "Adding user_allow_other to /etc/fuse.conf so containers can read the FUSE mount..."
    echo "user_allow_other" | sudo -n tee -a /etc/fuse.conf >/dev/null || true
fi

info "Mounting Google Drive at ${MOUNT_POINT} (foreground; Ctrl-C to unmount)..."
"$RCLONE_BIN" mount "${REMOTE_NAME}:" "$MOUNT_POINT" \
    --vfs-cache-mode writes \
    --file-perms 0777 \
    --dir-perms 0777 \
    --allow-other
