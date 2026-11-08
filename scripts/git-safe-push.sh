#!/usr/bin/env bash
# git-safe-push — the standard push for non-dell chaba checkouts.
#
# Dell's kanban-commit.timer pushes every ~15min, so a plain `git push`
# from any satellite checkout races it constantly. This wraps the
# standard retry loop: safe-pull (rebase+autostash, generated paths
# upstream-wins) then push, up to N attempts.
#
# Usage:  git-safe-push.sh [repo-dir]
# Env:    SAFE_PUSH_ATTEMPTS   retry count (default 4)
#         SAFE_PULL_UPSTREAM   upstream ref (default: @{upstream})
# Exit:   0 pushed; 1 gave up (manual resolution needed)
#
# No push credentials on this host? Fallbacks that need no local creds:
# bundle the work (`git bundle create /tmp/x.bundle origin/master..<branch>`),
# scp it to a push-capable host (tony-dell), there `git fetch /tmp/x.bundle
# <ref>` then `git push origin FETCH_HEAD:master` — or POST it to board-api
# /patch-relay for merge-sweep (scripts/board/dispatch_repos.py relay_session).
# Do NOT bake credentials into this checkout to work around the gap —
# card the missing cred (runner-push-cred-gap pattern).
set -uo pipefail

REPO="${1:-$PWD}"
cd "$REPO" || exit 2
HERE="$(dirname "$0")"
ATTEMPTS="${SAFE_PUSH_ATTEMPTS:-4}"
REMOTE="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null | cut -d/ -f1)"
REMOTE="${REMOTE:-origin}"
BRANCH="$(git branch --show-current)"

for i in $(seq 1 "$ATTEMPTS"); do
  if git push -q "$REMOTE" "$BRANCH" 2>/dev/null; then
    echo "git-safe-push: pushed $BRANCH -> $REMOTE (attempt $i)"
    exit 0
  fi
  echo "git-safe-push: push raced upstream, rebasing (attempt $i/$ATTEMPTS)" >&2
  "$HERE/git-safe-pull.sh" "$REPO" >/dev/null 2>&1 || {
    echo "git-safe-push: safe-pull failed — manual resolution needed" >&2
    exit 1
  }
done
echo "git-safe-push: gave up after $ATTEMPTS attempts" >&2
exit 1
