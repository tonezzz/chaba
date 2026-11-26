#!/usr/bin/env bash
# chaba-board-commit entrypoint (containerized kanban-commit.service).
# Runs the served-checkout sweeper, then reproduces the old unit's
# ExecStartPost kick of chaba-repo-sync.service on a best-effort basis —
# systemctl does not exist inside the container, so the kick only fires
# if this ever runs on the host; the 15-min chaba-repo-sync.timer covers
# the same convergence either way.
set -uo pipefail

"$HOME/CascadeProjects/chaba-tony-dell/scripts/board/kanban-commit.sh"
rc=$?

systemctl --user start --no-block chaba-repo-sync.service 2>/dev/null || true
exit "$rc"
