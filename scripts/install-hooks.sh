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
# Also stamps a per-checkout role marker (--role): writes `<gitdir>/chaba-role`
# which the pre-commit checkout-role guard reads. The marker lives in the
# per-worktree gitdir on purpose — `git config` is SHARED across linked
# worktrees (a role on the exec checkout would leak into every dispatch
# worktree hanging off it and block their commits). exec/readonly checkouts
# BLOCK commits (job units run from them; nothing should be committed
# there), other values are informational for check-single-writer.sh.
# Absent marker = legacy warn-only. Roles: served exec readonly job
# branch experiment.
#
# Usage:
#   install-hooks.sh [repo-path ...]   apply to each checkout (default: cwd)
#   install-hooks.sh --all             apply to every ~/CascadeProjects/chaba*
#                                       checkout
#   install-hooks.sh --role exec ~/CascadeProjects/chaba
#                                      also stamp the role on the targets
set -uo pipefail

role=""
targets=()
if [ "${1:-}" = "--role" ]; then
    role="${2:?--role needs a value (served|exec|readonly|job|branch|experiment)}"
    shift 2
fi
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
    # card-union merge driver (incident 2026-10-23, card
    # kanban-commit-reconcile-rebase-deadlocks-4d95a9): manual git
    # merge/pull in this checkout union-merges card YAML conflicts
    # instead of stopping on them. git-safe-pull.sh also self-arms.
    if [ -f "$top/scripts/board/merge-card-yaml.py" ]; then
        git -C "$repo" config merge.card-union.driver \
            "python3 $top/scripts/board/merge-card-yaml.py %O %A %B"
        gd="$(git -C "$repo" rev-parse --absolute-git-dir)"
        aline='docs/ssot/kanban/cards/*.yml merge=card-union'
        mkdir -p "$gd/info"
        grep -qxF "$aline" "$gd/info/attributes" 2>/dev/null \
            || echo "$aline" >> "$gd/info/attributes"
    fi
    role_msg=""
    if [ -n "$role" ]; then
        echo "$role" > "$(git -C "$repo" rev-parse --absolute-git-dir)/chaba-role"
        role_msg=", chaba-role=$role"
    fi
    echo "install-hooks: $top -> core.hooksPath=$hooks_path, pull.rebase=true, rebase.autoStash=true$role_msg"
done
exit $rc
