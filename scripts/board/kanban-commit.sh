#!/usr/bin/env bash
# kanban-commit — persist live board edits (board-api/kanban-dispatch writes)
# and generated focus-inbox state into git from the SERVED checkout. Runs
# from kanban-commit.timer every 15 min (RandomizedDelaySec staggers it).
#
# Single-writer rule (card kanban-commit-single-writer): chaba-tony-dell is
# the ONLY checkout with a periodic auto-committer. Other checkouts still
# make job-scoped commits (kanban-sync worktree, gh-runs-watch), but sweep
# commits happen here alone — sibling checkouts are audited by
# scripts/check-single-writer.sh and warned by the pre-commit hook.
#
# Scoped `git add` of generated dirs — never touches sessions' dirty files.
# Pulls go through git-safe-pull.sh: untracked files colliding with incoming
# upstream paths are resolved before the rebase (identical -> dropped,
# different -> renamed aside as <name>.local-<ts>), and rebase conflicts
# under generated dirs resolve upstream-wins. Result: pull --rebase
# completes unattended even in the untracked-collision case.
set -uo pipefail
REPO="${KANBAN_REPO:-$HOME/CascadeProjects/chaba-tony-dell}"
GENERATED_RE='^(docs/ssot/kanban/|docs/ssot/focus-inbox/|stacks/web/public/apps/board/)'
PUSH_RETRIES="${KANBAN_PUSH_RETRIES:-3}"
SAFE_PULL="$(cd "$(dirname "$0")" && pwd)/../git-safe-pull.sh"
cd "$REPO" || exit 1

for d in docs/ssot/kanban/ docs/ssot/focus-inbox/ stacks/web/public/apps/board/; do
    [ -d "$d" ] && git add "$d" 2>/dev/null
done
git diff --cached --quiet && exit 0   # nothing staged

git -c user.name="kanban-bot" -c user.email="kanban-bot@chaba.local" \
    commit -qm "board: live card updates ($(date '+%F %H:%M'))" || exit 1

attempt=0
while [ $attempt -lt "$PUSH_RETRIES" ]; do
    attempt=$((attempt + 1))
    if ! SAFE_PULL_GENERATED_RE="$GENERATED_RE" bash "$SAFE_PULL" "$REPO"; then
        echo "kanban-commit: pull --rebase needs manual resolution — next tick retries" >&2
        exit 1
    fi
    push_log="$(git push origin master 2>&1)"; rc=$?
    [ -n "$push_log" ] && echo "$push_log" | tail -2
    [ $rc -eq 0 ] && exit 0
    [ $attempt -lt "$PUSH_RETRIES" ] && sleep $((RANDOM % 8 + 2))
done
echo "kanban-commit: push failed after $PUSH_RETRIES attempts" >&2
exit 1
