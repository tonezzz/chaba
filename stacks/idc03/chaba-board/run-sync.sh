#!/usr/bin/env bash
# chaba-board-sync entrypoint (containerized kanban-sync.service).
# Prefers the dedicated worktree copy like the generated unit did
# (%h/CascadeProjects/chaba-kanban-sync/...), falling back to the served
# checkout so a missing worktree can still self-bootstrap (kanban-sync.sh
# creates $WT itself when absent).
set -euo pipefail

SERVED="$HOME/CascadeProjects/chaba-tony-dell/scripts/ada/kanban-sync.sh"
WT="$HOME/CascadeProjects/chaba-kanban-sync/scripts/ada/kanban-sync.sh"

if [ -f "$WT" ]; then
    exec /bin/bash "$WT"
fi
exec /bin/bash "$SERVED"
