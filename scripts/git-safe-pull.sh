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
#   3. autostash-pop conflicts under generated paths resolve to HEAD.
#      When every contested path resolves (nothing kept for a human),
#      the stash's contested hunks are superseded upstream-wins and its
#      clean hunks already landed — the retained entry is pure
#      resurrection fuel (card safe-pull-autostash-resurrection), so it
#      is archived to ~/.local/share/chaba-stash-archive/ and DROPPED.
#      Unresolved leftovers keep the stash for manual recovery.
#   4. periodic autostash GC: retained autostash entries older than
#      SAFE_PULL_AUTOSTASH_GC_DAYS (default 7) are archived the same way
#      then dropped — the pile is the reservoir stale card states
#      resurrect from. Named (human) stashes are never touched.
#   5. on exit (any path), scripts/board/reconcile-local-conflicts.py
#      folds each card .local-conflict-* back into its canonical card —
#      the preserved side usually holds a board write that raced the
#      pull. Merge failures keep the file and flag the card in review.
#
# Usage:  git-safe-pull.sh [repo-dir]
# Env:    SAFE_PULL_UPSTREAM          upstream ref (default: @{upstream}
#                                     or origin/master)
#         SAFE_PULL_GENERATED_RE      regex of upstream-wins paths
#                                     (default: ^docs/ssot/)
#         SAFE_PULL_AUTOSTASH_GC_DAYS drop autostash entries older than
#                                     N days (default 7; 0 disables GC)
#         SAFE_PULL_STASH_ARCHIVE     patch archive dir for dropped
#                                     stashes (default:
#                                     ~/.local/share/chaba-stash-archive)
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
GC_DAYS="${SAFE_PULL_AUTOSTASH_GC_DAYS:-7}"
ARCHIVE_DIR="${SAFE_PULL_STASH_ARCHIVE:-$HOME/.local/share/chaba-stash-archive}"

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
  # git-path is worktree-aware — `.git/rebase-merge` misses linked
  # worktrees where .git is a file, not a directory.
  local gd
  gd="$(git rev-parse --git-dir 2>/dev/null)" || return 1
  [ -d "$gd/rebase-merge" ] || [ -d "$gd/rebase-apply" ]
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

# Patch-archive a stash entry before dropping it — the safety net the
# manual GC used (patches in ~/.local/share/chaba-stash-archive/).
# Prints the path on success; non-zero when the archive could not be
# written (the caller decides whether the drop is still safe).
_archive_stash() {
  local ref="$1" why="$2" sha ts name dest
  sha="$(git rev-parse -q --verify "$ref" 2>/dev/null)" || return 1
  ts="$(git show -s --format=%cd --date=format:%Y%m%d-%H%M%S "$ref" 2>/dev/null)"
  name="$(echo "$ref" | tr -c 'A-Za-z0-9' '-')"
  dest="$ARCHIVE_DIR/${ts:-unknown}-${name}-${sha:0:8}-${why}.patch"
  mkdir -p "$ARCHIVE_DIR" 2>/dev/null || return 1
  {
    echo "# archived $(date '+%Y-%m-%d %H:%M:%S') on $(hostname 2>/dev/null) — $why"
    echo "# $ref: $(git show -s --format=%s "$ref" 2>/dev/null)"
    git stash show -p "$ref"
  } > "$dest" 2>/dev/null || { rm -f "$dest"; return 1; }
  echo "git-safe-pull: archived $ref -> $dest" >&2
}

# Drop the retained autostash when its pop conflicts all resolved to
# HEAD: contested hunks were superseded upstream-wins and clean hunks
# are already in the worktree, so the entry only feeds the resurrection
# pile. Archive first, then drop — but only when stash@{0} is the entry
# this pull created (a pre-existing or named stash is left alone).
_drop_resolved_autostash() {
  local sha msg
  sha="$(git rev-parse -q --verify 'stash@{0}' 2>/dev/null)" || return 0
  [ "$sha" != "$PRE_STASH_SHA" ] || return 0
  msg="$(git stash list | head -1)"; msg="${msg#*: }"
  case "$msg" in
    *autostash*|*"Auto stash"*) ;;
    *) return 0 ;;
  esac
  _archive_stash 'stash@{0}' "resolved-pop" || true
  git stash drop -q 'stash@{0}' \
    && echo "git-safe-pull: dropped autostash ${sha:0:8} — pop conflicts all resolved to HEAD, entry superseded" >&2
}

# Periodic GC — the retained-autostash pile is the reservoir the card
# resurrection waves drew from (card safe-pull-autostash-resurrection).
# Autostash entries older than GC_DAYS are past their recovery window:
# archive the patch, then drop. Drops run highest-index-first so live
# stash@{n} numbering never shifts under a pending target.
_gc_autostash() {
  [ "${GC_DAYS:-0}" -gt 0 ] 2>/dev/null || return 0
  local cutoff=$(( $(date +%s) - GC_DAYS * 86400 ))
  local drops=() gd ct sha gs
  while read -r gd ct sha gs; do
    [ -n "$gd" ] || continue
    case "$gs" in
      *autostash*|*"Auto stash"*) ;;
      *) continue ;;
    esac
    [ "$ct" -lt "$cutoff" ] 2>/dev/null || continue
    drops+=("$gd|$ct")
  done < <(git stash list --format='%gd %ct %H %gs' 2>/dev/null)
  local i ref ago
  for (( i=${#drops[@]}-1; i>=0; i-- )); do
    ref="${drops[$i]%%|*}"
    ago="${drops[$i]#*|}"
    _archive_stash "$ref" "gc" \
      || { echo "git-safe-pull: GC skipped $ref — archive failed" >&2; continue; }
    git stash drop -q "$ref" \
      && echo "git-safe-pull: GC'd $ref — autostash older than ${GC_DAYS}d ($(date -d "@$ago" '+%Y-%m-%d' 2>/dev/null))" >&2
  done
}

_resolve_autostash_pop() {
  # A failed autostash pop leaves unmerged entries + a retained stash.
  # Generated paths resolve to HEAD; anything else stays for a human.
  local p bad=0 saw=0
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    saw=1
    if [[ "$p" =~ $GENERATED_RE ]]; then
      if git checkout HEAD -- "$p" 2>/dev/null; then
        git reset -q HEAD -- "$p" 2>/dev/null || true
      else
        # upstream deleted the path — accept the deletion
        git rm -qf -- "$p" 2>/dev/null || true
      fi
    else
      echo "git-safe-pull: autostash pop conflict kept for manual merge: $p" >&2
      bad=1
    fi
  done < <(git diff --name-only --diff-filter=U 2>/dev/null)
  if [ $bad -eq 1 ]; then
    git stash list | head -1 >&2
  elif [ $saw -eq 1 ] \
       && [ -z "$(git diff --name-only --diff-filter=U 2>/dev/null)" ]; then
    _drop_resolved_autostash
  fi
  return 0
}

_resolve_untracked_collisions

# Snapshot the stash tip pre-pull so post-pop code can tell the entry
# this pull's autostash created from pre-existing stashes.
PRE_STASH_SHA="$(git rev-parse -q --verify refs/stash 2>/dev/null || true)"

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

# Every pull doubles as the periodic GC tick — dell's kanban-commit.timer
# runs this every ~15min, satellites hit it through git-safe-push.
_gc_autostash

# Autostash pops merge cleanly even when they shouldn't — the stash's
# stale card `column:` fields re-apply over the rebased tree while newer
# comms land at the bottom (resurrection waves, card
# git-autostash-column-guard). HEAD's committed column wins; everything
# else the pop merged stays.
COLGUARD="$REPO/scripts/board/card-column-guard.py"
[ -f "$COLGUARD" ] && python3 "$COLGUARD" "$REPO" || true

# Success means upstream is now an ancestor of HEAD (or unresolvable).
if git rev-parse --verify -q "$UPSTREAM" >/dev/null 2>&1 \
   && ! git merge-base --is-ancestor "$UPSTREAM" HEAD 2>/dev/null; then
  echo "git-safe-pull: pull did not complete — upstream not in HEAD" >&2
  exit 1
fi
exit 0
