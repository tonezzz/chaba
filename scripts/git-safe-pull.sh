#!/usr/bin/env bash
# git-safe-pull — `git pull --rebase --autostash` hardened for unattended use.
#
# The recurring stall (card kanban-commit-single-writer): autostash only
# covers TRACKED changes, so a pull that adds a file already present as
# untracked dies with "untracked working tree files would be overwritten"
# and waits for a human. This script removes the stall classes:
#
#   1. fetch, then walk every incoming upstream path and resolve untracked
#      blockers BEFORE the pull: identical content -> drop the local file
#      (upstream wins, nothing lost); different -> rename aside to
#      <path>.local-<ts> so the pull proceeds and nothing is silently lost.
#      An untracked file sitting where upstream needs a directory is moved
#      aside the same way.
#   2. pull --rebase --autostash; conflicts limited to generated paths
#      (SAFE_PULL_GENERATED_RE) resolve upstream-wins (--ours mid-rebase),
#      preserving the dropped local side as <path>.local-conflict-<ts>.
#      Conflicts outside generated paths abort the rebase and exit 1 —
#      manual resolution, next run retries.
#   3. autostash-pop conflicts under generated paths resolve to HEAD; the
#      stash entry is always retained for recovery.
#   4. on exit (any path), scripts/board/reconcile-local-conflicts.py
#      folds each card .local-conflict-* back into its canonical card —
#      the preserved side usually holds a board write that raced the
#      pull. Merge failures keep the file and flag the card in review.
#
# Usage:  git-safe-pull.sh [repo-dir]
# Env:    SAFE_PULL_UPSTREAM      upstream ref (default: @{upstream} or
#                                 origin/master)
#         SAFE_PULL_GENERATED_RE  regex of upstream-wins paths
#                                 (default: ^docs/ssot/)
# Exit:   0 = HEAD now contains upstream (or pull not needed);
#         1 = needs manual resolution; 2 = not a repo.
set -uo pipefail

REPO="${1:-$PWD}"
REPO_OK=0
RECONCILE="$REPO/scripts/board/reconcile-local-conflicts.py"

# Post-pull/step reconcile: fold each card .local-conflict-* file back
# into its canonical card (the board write that raced the rebase).
# Runs under a trap so aborted rebases still reconcile the conflict
# files their resolved steps produced. Best-effort: a reconcile
# failure never fails the pull — the conflict file stays and the card
# is flagged in review (card kanban-local-conflict-reconciler).
_post_pull_reconcile() {
  [ "$REPO_OK" = 1 ] && [ -f "$RECONCILE" ] || return 0
  python3 "$RECONCILE" "$REPO" || true
}
trap _post_pull_reconcile EXIT

cd "$REPO" 2>/dev/null || { echo "git-safe-pull: no repo $REPO" >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "git-safe-pull: $REPO is not a git worktree" >&2; exit 2; }
REPO_OK=1

TS="$(date '+%Y%m%d-%H%M%S')"
GENERATED_RE="${SAFE_PULL_GENERATED_RE:-^docs/ssot/}"

if [ -n "${SAFE_PULL_UPSTREAM:-}" ]; then
  UPSTREAM="$SAFE_PULL_UPSTREAM"
else
  UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' \
    2>/dev/null || echo origin/master)"
fi
REMOTE="${UPSTREAM%%/*}"
REF="${UPSTREAM#*/}"
[ "$REF" = "$REMOTE" ] && REF=""   # upstream without slash (unlikely)

git fetch -q "$REMOTE" ${REF:+"$REF"} >/dev/null 2>&1 \
  || git fetch -q "$REMOTE" >/dev/null 2>&1 || true

_is_tracked() { git ls-files --error-unmatch -- "$1" >/dev/null 2>&1; }

_aside() { # preserve an untracked blocker under a collision suffix
  local p="$1" dest="${1}.local-${TS}"
  mv -- "$p" "$dest" \
    && echo "git-safe-pull: untracked $p collides with upstream — moved to $dest" >&2
}

# Resolve untracked paths that incoming upstream changes would overwrite.
# A directory at a leading prefix never blocks; a file at any prefix does,
# and a directory at the full path blocks when upstream adds a file there.
_resolve_untracked_collisions() {
  git rev-parse --verify -q "$UPSTREAM" >/dev/null 2>&1 || return 0
  local p check
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    check="$p"
    while :; do
      if [ -e "$check" ] && ! _is_tracked "$check"; then
        if [ -d "$check" ]; then
          # dir at the incoming file's own path blocks only if it holds no
          # tracked files (a dir at a shorter prefix is normal, never blocks)
          if [ "$check" = "$p" ] \
             && [ -z "$(git ls-files -- "$check" | head -1)" ]; then
            _aside "$check"
          fi
        elif [ "$check" = "$p" ]; then
          if git show "$UPSTREAM:$p" 2>/dev/null | cmp -s - "$check"; then
            rm -- "$check"   # identical — upstream wins, nothing lost
          else
            _aside "$check"
          fi
        else
          _aside "$check"    # untracked file where upstream needs a dir
        fi
      fi
      [ "$check" = "${check%/*}" ] && break
      check="${check%/*}"
    done
  done < <(git diff --name-only "HEAD...$UPSTREAM" 2>/dev/null)
}

_rebase_in_progress() {
  [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]
}

# Returns 0 when all unmerged paths were generated (resolved upstream-wins).
_resolve_generated_conflicts() {
  local p bad=0
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    if [[ "$p" =~ $GENERATED_RE ]]; then
      # stage 3 = the local commit being replayed — preserve it aside.
      # Same path can conflict in several rebase steps inside one $TS
      # second; suffix rather than overwrite a preserved side.
      local dest="$p.local-conflict-$TS" n=1
      while [ -e "$dest" ]; do
        n=$((n + 1)); dest="$p.local-conflict-$TS-$n"
      done
      git show ":3:$p" > "$dest" 2>/dev/null || true
      if git checkout --ours -- "$p" 2>/dev/null; then
        git add -- "$p"
      else
        # upstream deleted the file — accept the deletion
        git rm -qf -- "$p" 2>/dev/null || git add -- "$p" 2>/dev/null || true
      fi
    else
      echo "git-safe-pull: conflict outside generated paths: $p" >&2
      bad=1
    fi
  done < <(git diff --name-only --diff-filter=U 2>/dev/null)
  return $bad
}

_resolve_autostash_pop() {
  # A failed autostash pop leaves unmerged entries + a retained stash.
  # Generated paths resolve to HEAD; anything else stays for a human.
  local p bad=0
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    if [[ "$p" =~ $GENERATED_RE ]]; then
      git checkout HEAD -- "$p" 2>/dev/null && git reset -q HEAD -- "$p" 2>/dev/null
    else
      echo "git-safe-pull: autostash pop conflict kept for manual merge: $p" >&2
      bad=1
    fi
  done < <(git diff --name-only --diff-filter=U 2>/dev/null)
  [ $bad -eq 1 ] && git stash list | head -1 >&2
  return 0
}

_resolve_untracked_collisions

git pull --rebase --autostash "$REMOTE" ${REF:+"$REF"} >/dev/null 2>&1 || true

guard=0
while _rebase_in_progress; do
  guard=$((guard + 1))
  if [ $guard -gt 25 ]; then
    git rebase --abort >/dev/null 2>&1
    echo "git-safe-pull: too many conflicted steps — aborted" >&2
    exit 1
  fi
  if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null)" ]; then
    if ! _resolve_generated_conflicts; then
      git rebase --abort >/dev/null 2>&1
      exit 1
    fi
    GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 \
      || { git rebase --abort >/dev/null 2>&1; exit 1; }
  else
    # resolved or empty step — continue; if the commit became empty, skip it
    GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 \
      || git rebase --skip >/dev/null 2>&1 \
      || { git rebase --abort >/dev/null 2>&1; exit 1; }
  fi
done

_resolve_autostash_pop

# Success means upstream is now an ancestor of HEAD (or unresolvable).
if git rev-parse --verify -q "$UPSTREAM" >/dev/null 2>&1 \
   && ! git merge-base --is-ancestor "$UPSTREAM" HEAD 2>/dev/null; then
  echo "git-safe-pull: pull did not complete — upstream not in HEAD" >&2
  exit 1
fi
exit 0
