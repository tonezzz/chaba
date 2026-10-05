#!/usr/bin/env bash
# install-hooks — enable the versioned pre-commit hook + sane pull defaults
# in a checkout (card kanban-commit-single-writer).
#
# The pre-commit hook (warn-only outside the served checkout) lives in
# .husky/pre-commit. Husky's own shims only exist after `npm install`, so
# this script points core.hooksPath at .husky directly — the hook is plain
# bash and runs fine without husky/node.
#
# Also sets the "always-rebase-with-autostash" defaults so a manual
# `git pull` in that checkout behaves like the unattended path.
#
# Usage:
#   install-hooks.sh [repo-path ...]   apply to each checkout (default: cwd)
#   install-hooks.sh --all             apply to every ~/CascadeProjects/chaba*
#                                       checkout
set -uo pipefail

targets=()
if [ "${1:-}" = "--all" ]; then
    for d in "$HOME"/CascadeProjects/chaba*; do
        if [ -d "$d/.git" ] || [ -f "$d/.git" ]; then targets+=("$d"); fi
    done
elif [ $# -gt 0 ]; then
    targets=("$@")
else
    targets=("$PWD")
fi

rc=0
for repo in "${targets[@]}"; do
    if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "install-hooks: $repo is not a git worktree — skipped" >&2
        rc=1
        continue
    fi
    top="$(git -C "$repo" rev-parse --show-toplevel)"
    if [ -f "$top/.husky/_/pre-commit" ]; then
        hooks_path=".husky/_"        # husky installed — keep its shims
    elif [ -f "$top/.husky/pre-commit" ]; then
        hooks_path=".husky"          # plain-bash hook, no husky needed
    else
        echo "install-hooks: $top has no .husky/pre-commit — skipped" >&2
        rc=1
        continue
    fi
    git -C "$repo" config core.hooksPath "$hooks_path"
    git -C "$repo" config pull.rebase true
    git -C "$repo" config rebase.autoStash true
    echo "install-hooks: $top -> core.hooksPath=$hooks_path, pull.rebase=true, rebase.autoStash=true"
done
exit $rc
