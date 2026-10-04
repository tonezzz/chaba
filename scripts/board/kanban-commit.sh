#!/usr/bin/env bash
# kanban-commit — persist live board edits (board-api/kanban-dispatch writes)
# into git from the served checkout. Runs from kanban-commit.timer every 15 min.
# Scoped `git add` — never touches other sessions' dirty files.
set -uo pipefail
REPO="${KANBAN_REPO:-$HOME/CascadeProjects/chaba-tony-dell}"
cd "$REPO" || exit 1

git add docs/ssot/kanban/ stacks/web/public/apps/board/ 2>/dev/null
git diff --cached --quiet && exit 0   # nothing staged

git -c user.name="kanban-bot" -c user.email="kanban-bot@chaba.local" \
    commit -m "board: live card updates ($(date '+%F %H:%M'))" >/dev/null || exit 1

git pull --rebase --autostash >/dev/null 2>&1 || true
git push origin master 2>&1 | tail -2
