#!/usr/bin/env bash
set -euo pipefail
# Deploy notebooklm-rest source to tony-dell, rebuild the image, restart.
# Live source dir: ~/.local/share/notebooklm/notebooklm-rest-api (NOT in git —
# this stack dir is the canonical copy; keep it in sync after live edits).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LIVE_DIR='~/.local/share/notebooklm/notebooklm-rest-api'
HOST="${1:-tony-dell}"

scp "$SCRIPT_DIR/app.py" "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR/requirements.txt" \
    "$HOST:.local/share/notebooklm/notebooklm-rest-api/"
scp "$SCRIPT_DIR/notebooklm-rest.container" \
    "$HOST:.config/containers/systemd/notebooklm-rest.container"

ssh "$HOST" 'cd ~/.local/share/notebooklm/notebooklm-rest-api \
    && podman build -t localhost/notebooklm-rest . \
    && systemctl --user daemon-reload \
    && systemctl --user restart notebooklm-rest \
    && sleep 5 && systemctl --user is-active notebooklm-rest \
    && curl -sf http://127.0.0.1:3011/health/auth | head -c 200'
echo
echo "notebooklm-rest deployed on $HOST"
