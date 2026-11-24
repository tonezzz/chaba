#!/usr/bin/env bash
# Install/refresh the chaba-board quadlet stack on THIS host (idc03).
#
#   bash install.sh            build image + install quadlets (no cutover)
#   bash install.sh --cutover  also disable the legacy units and start
#                              the quadlet units — run ONLY with approval;
#                              this is the production write-path switch.
#
# Steps:
#   1. podman build -t localhost/chaba-board:latest <this dir>
#   2. install wrapper scripts -> ~/.config/containers/chaba-board/
#   3. install quadlets        -> ~/.config/containers/systemd/
#   4. daemon-reload; with --cutover, disable legacy units first.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
QUAD_DIR="$HOME/.config/containers/systemd"
BIN_DIR="$HOME/.config/containers/chaba-board"
CUTOVER=0
[ "${1:-}" = "--cutover" ] && CUTOVER=1

command -v podman >/dev/null || { echo "podman not found" >&2; exit 1; }

if ! podman image exists localhost/chaba-board:latest; then
    echo ">> building localhost/chaba-board:latest"
    podman build -t localhost/chaba-board:latest "$HERE"
fi

mkdir -p "$QUAD_DIR" "$BIN_DIR"
install -m 0755 "$HERE"/run-api.sh "$HERE"/run-sync.sh "$HERE"/run-commit.sh "$BIN_DIR/"
install -m 0644 "$HERE"/chaba-board-*.container "$HERE"/chaba-board-*.timer "$QUAD_DIR/"

# Legacy units this stack replaces (source: systemd/*.service|timer and
# systemd/generated/idc03/kanban-sync.*).
LEGACY_UNITS="chaba-board-api.service chaba-board-render.service chaba-board-render.timer kanban-sync.service kanban-sync.timer kanban-commit.service kanban-commit.timer"

systemctl --user daemon-reload

if [ "$CUTOVER" -eq 1 ]; then
    echo ">> cutover: disabling legacy units"
    # shellcheck disable=SC2086
    systemctl --user disable --now $LEGACY_UNITS 2>/dev/null || true
    echo ">> starting quadlet units"
    systemctl --user enable --now chaba-board-api.service
    systemctl --user enable --now chaba-board-render.timer
    systemctl --user enable --now chaba-board-sync.timer
    systemctl --user enable --now chaba-board-commit.timer
else
    cat <<EOF
>> quadlets installed (no cutover). To switch production over:
   bash $HERE/install.sh --cutover
Legacy units left running: $LEGACY_UNITS
EOF
fi

sleep 2
echo ">> verify:"
systemctl --user is-active chaba-board-api.service || true
curl -sf -m 5 http://127.0.0.1:8787/health && echo " <- board-api /health ok" || echo "!! /health not answering yet"
systemctl --user list-timers 'chaba-board-*' --no-pager || true
