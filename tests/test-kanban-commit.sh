#!/usr/bin/env bash
# tests/test-kanban-commit.sh — verification for card kanban-commit-single-writer.
#
# Self-contained: builds a bare origin + two clones ("served" = the checkout
# kanban-commit watches, "other" = a parallel session checkout) in a tmpdir
# and exercises the required cases:
#
#   A. two parallel sessions -> kanban-commit's pull --rebase completes while
#      a second writer pushes underneath it; both histories land.
#   B. untracked-collision (different content) -> pull completes unattended,
#      upstream wins, local copy preserved as <name>.local-<ts>.
#   C. untracked-collision (identical content) -> silently absorbed.
#   D. pre-commit hook warns outside the served checkout for focus-inbox
#      writes and >N-commit divergence; stays silent in the served checkout.
#   E. check-single-writer.sh lint reports dirty/divergent non-served checkouts.
#
# Usage: bash tests/test-kanban-commit.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
KANBAN_COMMIT="$ROOT/scripts/board/kanban-commit.sh"
SAFE_PULL="$ROOT/scripts/git-safe-pull.sh"
INSTALL_HOOKS="$ROOT/scripts/install-hooks.sh"
CHECK_SW="$ROOT/scripts/check-single-writer.sh"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "ok   $*"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL $*"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }

# --- fixture ---------------------------------------------------------------
git init --bare --initial-branch=master "$TMP/origin.git" >/dev/null 2>&1
git clone -q "$TMP/origin.git" "$TMP/seed"
(
  cd "$TMP/seed"
  git config user.email t@t; git config user.name t
  mkdir -p docs/ssot/kanban/cards docs/ssot/focus-inbox \
          stacks/web/public/apps/board .husky
  # git doesn't track empty dirs — seed a placeholder so clones get them
  for d in docs/ssot/kanban/cards docs/ssot/focus-inbox \
           stacks/web/public/apps/board; do : > "$d/.gitkeep"; done
  echo "title: kanban" > docs/ssot/kanban/ssot.kanban.yml
  cp "$ROOT/.husky/pre-commit" .husky/pre-commit
  git add -A; git commit -qm seed
  git push -q origin master
)
git clone -q "$TMP/origin.git" "$TMP/served"
git clone -q "$TMP/origin.git" "$TMP/other"
for r in served other; do
  git -C "$TMP/$r" config user.email t@t
  git -C "$TMP/$r" config user.name t
done

export KANBAN_REPO="$TMP/served"
export CHABA_SERVED_CHECKOUT="$TMP/served"
export CHABA_CHECKOUTS=""          # keep the sibling scan quiet in tests
export CHABA_DIVERGENCE_N=2        # small N so the warning is easy to trip

# --- A: two parallel sessions ----------------------------------------------
echo "# live board edit" >> "$TMP/served/docs/ssot/kanban/ssot.kanban.yml"
echo "title: card a"  >  "$TMP/served/docs/ssot/kanban/cards/card-a.yml"
(
  cd "$TMP/other" || exit 1
  for i in 1 2 3; do
    echo "title: other-$i" > "docs/ssot/kanban/cards/card-b$i.yml"
    git add -A && git commit -qm "other commit $i" || exit 1
    git push -q origin master 2>/dev/null \
      || { bash "$SAFE_PULL" . >/dev/null 2>&1 && git push -q origin master; } \
      || exit 1
    sleep 0.2
  done
) &
BGPID=$!
bash "$KANBAN_COMMIT" >/dev/null 2>"$TMP/a.err"; rc_a=$?
wait $BGPID; rc_b=$?
check "A: kanban-commit exits 0 under parallel writer" "[ $rc_a -eq 0 ]"
check "A: parallel session writer finished"             "[ $rc_b -eq 0 ]"
check "A: board commit reached origin" \
  "git -C '$TMP/origin.git' log master --format=%s | grep -q 'board: live card updates'"
check "A: parallel commits reached origin" \
  "git -C '$TMP/origin.git' log master --format=%s | grep -q 'other commit 3'"
check "A: served replayed onto upstream" \
  "git -C '$TMP/served' merge-base --is-ancestor origin/master HEAD"

# --- B: untracked collision, different content ------------------------------
# Path deliberately OUTSIDE kanban-commit's scoped add so the file stays
# untracked — that is the class autostash cannot cover (the reported stall).
mkdir -p "$TMP/served/docs/ssot/jobs/kanban" "$TMP/other/docs/ssot/jobs/kanban"
echo "LOCAL version" > "$TMP/served/docs/ssot/jobs/kanban/2026-01-01-collision.yml"
echo "# board tick"    >> "$TMP/served/docs/ssot/kanban/ssot.kanban.yml"
(
  cd "$TMP/other" || exit 1
  bash "$SAFE_PULL" . >/dev/null 2>&1
  echo "UPSTREAM version" > docs/ssot/jobs/kanban/2026-01-01-collision.yml
  git add -A && git commit -qm "other adds colliding inbox file"
  git push -q origin master || exit 1
)
bash "$KANBAN_COMMIT" >/dev/null 2>"$TMP/b.err"; rc_b=$?
check "B: pull --rebase completed despite untracked collision" "[ $rc_b -eq 0 ]"
check "B: upstream content won in served checkout" \
  "grep -q 'UPSTREAM version' '$TMP/served/docs/ssot/jobs/kanban/2026-01-01-collision.yml'"
check "B: local version preserved aside" \
  "ls '$TMP/served/docs/ssot/jobs/kanban/2026-01-01-collision.yml.local-'* >/dev/null 2>&1"
check "B: aside kept local content" \
  "grep -q 'LOCAL version' '$TMP/served/docs/ssot/jobs/kanban/2026-01-01-collision.yml.local-'*"
check "B: served HEAD contains upstream" \
  "git -C '$TMP/served' merge-base --is-ancestor origin/master HEAD"
check "B: no rebase left in progress" \
  "! git -C '$TMP/served' rev-parse -q --verify REBASE_HEAD >/dev/null"

# --- C: untracked collision, identical content ------------------------------
echo "identical" > "$TMP/served/docs/ssot/jobs/kanban/2026-01-02-identical.yml"
echo "# tick" >> "$TMP/served/docs/ssot/kanban/ssot.kanban.yml"
(
  cd "$TMP/other" || exit 1
  bash "$SAFE_PULL" . >/dev/null 2>&1
  echo "identical" > docs/ssot/jobs/kanban/2026-01-02-identical.yml
  git add -A && git commit -qm "identical inbox file"
  git push -q origin master || exit 1
)
bash "$KANBAN_COMMIT" >/dev/null 2>"$TMP/c.err"; rc_c=$?
check "C: identical untracked collision absorbed" "[ $rc_c -eq 0 ]"
check "C: no aside file for identical collision" \
  "! ls '$TMP/served/docs/ssot/jobs/kanban/2026-01-02-identical.yml.local-'* >/dev/null 2>&1"

# --- D: pre-commit hook ------------------------------------------------------
bash "$INSTALL_HOOKS" "$TMP/other"  >/dev/null 2>&1
bash "$INSTALL_HOOKS" "$TMP/served" >/dev/null 2>&1
check "D: install-hooks armed other checkout" \
  "[ -n \"\$(git -C '$TMP/other' config core.hooksPath)\" ]"
check "D: install-hooks set pull.rebase" \
  "[ \"\$(git -C '$TMP/other' config pull.rebase)\" = true ]"

# focus-inbox write outside served checkout -> warning
bash "$SAFE_PULL" "$TMP/other" >/dev/null 2>&1
printf 'title: draft\n' > "$TMP/other/docs/ssot/focus-inbox/hook-test.yml"
git -C "$TMP/other" add docs/ssot/focus-inbox/hook-test.yml
out_d="$(cd "$TMP/other" && git commit -m "inbox draft outside served" 2>&1)"
check "D: focus-inbox commit outside served warns" \
  "grep -qi 'single-writer' <<<\"$out_d\""
check "D: warning commit still succeeds (warn-only)" \
  "git -C '$TMP/other' log -1 --format=%s | grep -q 'inbox draft outside served'"

# served checkout stays silent for the same write
printf 'title: served-draft\n' > "$TMP/served/docs/ssot/focus-inbox/served-draft.yml"
git -C "$TMP/served" add docs/ssot/focus-inbox/served-draft.yml
out_s="$(cd "$TMP/served" && git commit -m "inbox draft in served" 2>&1)"
check "D: served checkout does not warn" "! grep -qi 'single-writer' <<<\"$out_s\""

# divergence: >N unpushed commits on master outside served -> warning
# (other already carries the earlier draft commit: ahead grows past N=2)
cd "$TMP/other" || exit 1
out_div=""
for i in 1 2 3; do
  echo "wip$i" >> wip.txt
  git add wip.txt
  out_div="$out_div$(git commit -qm "wip $i" 2>&1)"
done
cd - >/dev/null
check "D: >N unpushed commits warns about divergence" \
  "grep -qi 'unpushed commits ahead' <<<\"$out_div\""

# --- E: lint -----------------------------------------------------------------
printf 'title: stray\n' > "$TMP/other/docs/ssot/focus-inbox/stray.yml"
lint_out="$(CHABA_CHECKOUTS="$TMP/served $TMP/other" bash "$CHECK_SW" 2>&1)"
check "E: lint flags other checkout" \
  "grep -q 'WARN.*other' <<<\"$lint_out\""
check "E: lint reports uncommitted focus-inbox" \
  "grep -q 'uncommitted focus-inbox' <<<\"$lint_out\""
check "E: served checkout reports ok" \
  "grep -q 'ok.*served' <<<\"$lint_out\""

# --- F: YAML syntax guard ----------------------------------------------------
# A staged card that doesn't parse must never reach origin/master — the
# sweep refuses, files the alert card naming the file, and the same run
# recovers once the file is fixed (card
# guard-card-yaml-syntax-validation-at-wri).
printf 'id: bad\nnote: "unclosed\n  - key: nope\n' \
    > "$TMP/served/docs/ssot/kanban/cards/bad-card.yml"
printf 'id: good\ntitle: fine\n' \
    > "$TMP/served/docs/ssot/kanban/cards/good-card.yml"
bash "$KANBAN_COMMIT" >/dev/null 2>"$TMP/f.err"; rc_f=$?
check "F: kanban-commit refuses staged bad YAML" "[ $rc_f -ne 0 ]"
check "F: refusal names the YAML syntax error" \
  "grep -q 'YAML syntax errors' '$TMP/f.err'"
check "F: bad card did NOT reach origin/master" \
  "! git -C '$TMP/origin.git' show master:docs/ssot/kanban/cards/bad-card.yml >/dev/null 2>&1"
check "F: alert card filed in served checkout" \
  "grep -q 'yaml-syntax' '$TMP/served/docs/ssot/kanban/cards/ops-kanban-commit-guard.yml'"
printf 'id: bad\ntitle: fixed\n' \
    > "$TMP/served/docs/ssot/kanban/cards/bad-card.yml"
bash "$KANBAN_COMMIT" >/dev/null 2>"$TMP/f2.err"; rc_f2=$?
check "F: sweep recovers once YAML is fixed" "[ $rc_f2 -eq 0 ]"
check "F: fixed card pushed to origin/master" \
  "git -C '$TMP/origin.git' show master:docs/ssot/kanban/cards/bad-card.yml | grep -q 'fixed'"

# --- G: board write flock (board-api-writes-eaten-by-autostash-pops) ------
# safe-pull holds the board write flock across the pull so a board-api
# save() can never sit uncommitted when autostash fires. The wait is
# bounded: a wedged writer must not deadlock convergence — it logs and
# pulls anyway.
exec 9>"$TMP/board-api.lock"
flock 9
SAFE_PULL_BOARD_LOCK="$TMP/board-api.lock" SAFE_PULL_BOARD_LOCK_WAIT_S=1 \
  bash "$SAFE_PULL" "$TMP/served" >/dev/null 2>"$TMP/g.err"; rc_g=$?
check "G: safe-pull completes despite held board lock" "[ $rc_g -eq 0 ]"
check "G: held lock waited then bypassed with a log line" \
  "grep -q 'pulling anyway' '$TMP/g.err'"
flock -u 9
# free lock -> no warning, still exits 0
SAFE_PULL_BOARD_LOCK="$TMP/board-api.lock" \
  bash "$SAFE_PULL" "$TMP/served" >/dev/null 2>"$TMP/g2.err"; rc_g2=$?
check "G: free board lock -> clean pull" "[ $rc_g2 -eq 0 ]"
check "G: free lock -> no bypass warning" \
  "! grep -q 'pulling anyway' '$TMP/g2.err'"

# mutual exclusion end-to-end: a write landing while safe-pull waits on
# the lock is committed before the pull stashes — it survives in HEAD.
flock 9
(
  SAFE_PULL_BOARD_LOCK="$TMP/board-api.lock" \
  SAFE_PULL_BOARD_LOCK_WAIT_S=10 \
    bash "$SAFE_PULL" "$TMP/served" >/dev/null 2>"$TMP/g3.err"
  echo $? > "$TMP/g3.rc"
) &
GPID=$!
sleep 1   # safe-pull is blocked on the board lock
check "G: safe-pull still blocked while the lock is held" \
  "[ ! -f '$TMP/g3.rc' ]"
printf 'id: raced\ntitle: raced write\n' \
  > "$TMP/served/docs/ssot/kanban/cards/raced.yml"
git -C "$TMP/served" add docs/ssot/kanban/cards/raced.yml 2>/dev/null
git -C "$TMP/served" commit -qm "board-api write raced" 2>/dev/null
flock -u 9; exec 9>&-
wait $GPID
check "G: pull blocked until writer committed, then exited 0" \
  "[ \$(cat '$TMP/g3.rc') -eq 0 ]"
check "G: raced write survives the pull in HEAD" \
  "git -C '$TMP/served' show HEAD:docs/ssot/kanban/cards/raced.yml | grep -q 'raced write'"
check "G: no autostash retained for the raced write" \
  "! git -C '$TMP/served' stash list | grep -qi autostash"

echo
echo "passed: $PASS  failed: $FAIL"
[ $FAIL -eq 0 ]
