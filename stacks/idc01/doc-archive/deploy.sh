#!/usr/bin/env bash
set -euo pipefail
# Deploy doc-archive to idc01: copy source, build a venv, install the systemd
# USER unit. Idempotent. Does NOT touch master, git, or Drive content.
#
# Prereqs on idc01:
#   - ~/.config/secrets/doc-archive.env  (see doc-archive.env.example; 0600)
#   - ~/.config/rclone/rclone.conf with a [gdrive] section holding
#     client_id/client_secret/token (copied from tony-dell per the design doc)
#   - python3 >= 3.12 with venv
#
# Quadlet alternative: install doc-archive.container into
# ~/.config/containers/systemd/ and `podman build -t localhost/doc-archive`
# from APP_DIR instead of the venv+service steps below.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOST="${1:-idc01}"
APP_DIR='.local/share/doc-archive'

ssh "$HOST" "mkdir -p $APP_DIR .config/systemd/user .config/secrets"

scp "$SCRIPT_DIR/drive_client.py" "$SCRIPT_DIR/doc_archive.py" \
    "$SCRIPT_DIR/requirements.txt" "$HOST:$APP_DIR/"
scp "$SCRIPT_DIR/doc-archive.service" \
    "$HOST:.config/systemd/user/doc-archive.service"

ssh "$HOST" "set -e
    test -f .config/secrets/doc-archive.env || {
        echo 'MISSING .config/secrets/doc-archive.env — see doc-archive.env.example' >&2; exit 1; }
    test -f .config/rclone/rclone.conf || {
        echo 'MISSING .config/rclone/rclone.conf ([gdrive] creds) — copy from tony-dell' >&2; exit 1; }
    cd $APP_DIR
    python3 -m venv venv
    venv/bin/pip install --quiet -r requirements.txt
    systemctl --user daemon-reload
    systemctl --user enable --now doc-archive.service
    sleep 3
    systemctl --user is-active doc-archive.service
    BIND=\$(grep -E '^DOC_ARCHIVE_BIND=' .config/secrets/doc-archive.env | cut -d= -f2)
    PORT=\$(grep -E '^DOC_ARCHIVE_PORT=' .config/secrets/doc-archive.env | cut -d= -f2)
    curl -sf \"http://\${BIND:-100.74.146.0}:\${PORT:-11025}/health\""

echo
echo "doc-archive deployed on $HOST"
