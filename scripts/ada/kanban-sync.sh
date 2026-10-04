#!/bin/bash
# kanban-sync — one tick of the kanban <-> CMS loop.
#   1. ff-pull the dedicated worktree to origin/master
#   2. cms-auto-health: ada-cms-automation -> cms-auto-* cards (writes files)
#   3. commit + push ONLY cards/ changes the health check made
#   4. kanban-cms: render the live board into the dev-kanban CMS page
#
# Runs from a dedicated detached worktree so a busy/dirty main checkout
# (chaba-tony-dell) can never block it. Self-bootstraps the worktree.
# Push races with other sessions just defer to the next tick.
set -u

SRC=$HOME/CascadeProjects/chaba-tony-dell
WT=$HOME/CascadeProjects/chaba-kanban-sync

if [ ! -d "$WT" ]; then
    git -C "$SRC" fetch origin -q || exit 1
    git -C "$SRC" worktree add --detach "$WT" origin/master || exit 1
fi
cd "$WT" || exit 1
git fetch origin -q || { echo "fetch failed"; exit 1; }
git merge --ff-only origin/master || { echo "ff-pull failed"; exit 1; }

python3 scripts/ada/cms-auto-health.py || echo "health check failed (non-fatal)"

git add docs/ssot/kanban/cards/ 2>/dev/null
if ! git diff --cached --quiet 2>/dev/null; then
    git commit -qm "kanban: cms-auto-health sync $(date -Iseconds)
"
    git push -q origin HEAD:master || echo "push raced — next tick retries"
fi

python3 scripts/ada/kanban-cms.py
