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
#
# Guards (card kanban-commit-conflict-marker-guard, incident 2026-10-05):
# a failed `pull --rebase` below leaves the repo mid-rebase with <<<<<<< /
# ======= / >>>>>>> in card files; the next tick used to stage+commit them,
# and the poisoned YAML then killed render-board + kanban-dispatch on parse.
# Now: refuse to commit while a rebase/merge/cherry-pick is in progress, and
# refuse when `git diff --cached --check` reports leftover conflict markers.
# On refuse: log the files to the journal (stderr) and upsert a review-column
# ops card so the skip is visible on the board — this class is silent
# otherwise.
#
# Failure streak (incident 2026-10-23, card
# kanban-commit-reconcile-rebase-deadlocks-4d95a9): every nonzero exit
# bumps $gitdir/kanban-commit-fail-streak; at KANBAN_FAILURE_ALERT_AFTER
# (default 3 ≈ 45min) the ops alert card is flagged — the wedge that ran
# silent all day now surfaces on the board. A clean tick resets the
# counter; recovery after an alerted streak leaves a comms line on the
# alert card.
set -uo pipefail
REPO="${KANBAN_REPO:-$HOME/CascadeProjects/chaba-tony-dell}"
# Kept in sync with git-safe-pull.sh's default GENERATED_RE plus the
# board statics path: the writer checkout also has non-kanban producers
# (dev-system assess, host-roles writers) whose files collide on every
# autostash pop — a narrow kanban-only regex left those "for manual
# merge" and wedged the tree + spammed the ops-guard card each cycle.
GENERATED_RE='^(docs/ssot/|reports/SSOT_OPTIMIZATION_WARNINGS\.json$|stacks/web/public/apps/board/|docs/reports/education-maintenance/|docs/reports/lesson-audit/)'
# Auto-writer ownership boundary (incidents 4af10b4c5c and 56aac6476c):
# this sweep owns GENERATED board state only. It must never commit code or
# the hand-maintained SSOT prose — both used to ride in from a stale writer
# checkout and silently revert origin/master (OPS-1406 restore). The commit
# below is pathspec-limited to these paths, with the prose explicitly
# excluded, and the guard after `git add` refuses anything else staged.
GENERATED_PATHS=(
    "docs/ssot/"
    "reports/SSOT_OPTIMIZATION_WARNINGS.json"
    "stacks/web/public/apps/board/"
    "docs/reports/education-maintenance/"
    "docs/reports/lesson-audit/"
)
PROTECTED_PATH="docs/ssot/kanban/ssot.kanban.yml"
PUSH_RETRIES="${KANBAN_PUSH_RETRIES:-3}"
SAFE_PULL="$(cd "$(dirname "$0")" && pwd)/../git-safe-pull.sh"
cd "$REPO" || exit 1

ALERT_CARD_ID="ops-kanban-commit-guard"

alert_card() {
    # $1 = reason slug, $2 = detail line. Upserts the alert card under the
    # board write flock (direct card-YAML edits must hold it — board-api.py
    # docstring). Dedup: same note while open just bumps `updated`, so a
    # persistent poison doesn't spam comms every 15 min; a changed reason or
    # a re-hit after close appends comms and re-opens (column -> review).
    BAD_REASON="$1" BAD_NOTE="$2" python3 - "$REPO" "$ALERT_CARD_ID" <<'PY'
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

repo, cid = Path(sys.argv[1]), sys.argv[2]
reason, note = os.environ["BAD_REASON"], os.environ["BAD_NOTE"]
sys.path.insert(0, str(repo / "scripts/board"))
import card_io
card_path = repo / "docs/ssot/kanban/cards" / f"{cid}.yml"
now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
try:
    with open("/tmp/board-api.lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        card = yaml.safe_load(card_path.read_text()) \
            if card_path.exists() else {}
        if not isinstance(card, dict):
            card = {}
        comms = card.get("comms")
        if not isinstance(comms, list):
            card["comms"] = comms = []
        if card.get("column") == "done" or card.get("note") != note[:500]:
            comms.append({"at": now, "from": "chaba",
                          "text": f"commit refused ({reason}): {note}"[:500]})
        card.update(id=cid,
                    title="kanban-commit blocked: unsafe staged state",
                    column="review", note=note[:500], updated=now)
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_io.atomic_dump_card(card_path, card)
    render = repo / "scripts/render-board.py"
    if render.exists():
        # Tolerate failure — while a poisoned card exists the renderer
        # dies on yaml.safe_load; the alert still lands on the next
        # healthy render.
        subprocess.run([sys.executable, str(render)], cwd=repo,
                       check=False, timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception as e:  # alerting must never crash the commit loop
    print(f"kanban-commit: alert card write failed: {e}", file=sys.stderr)
PY
    # The alert card is a board write outside board-api — commit it now or
    # it sits dirty as autostash bait for the next pull on this checkout
    # (board-api-writes-eaten-by-autostash-pops-515009). Best-effort: a
    # mid-rebase tree refuses the commit and the write waits for the sweep.
    git add -- "docs/ssot/kanban/cards/${ALERT_CARD_ID}.yml" 2>/dev/null \
      && git -c user.name="kanban-bot" \
             -c user.email="kanban-bot@chaba.local" \
             commit --no-verify -qm \
             "board: kanban-commit alert (${1:-guard})" \
             -- "docs/ssot/kanban/cards/${ALERT_CARD_ID}.yml" 2>/dev/null \
      || true
}

gitdir=$(git rev-parse --git-dir)
STREAK_FILE="$gitdir/kanban-commit-fail-streak"
ALERT_AFTER="${KANBAN_FAILURE_ALERT_AFTER:-3}"

fail_tick() {
    # Bump the consecutive-failure counter; at ALERT_AFTER flag the ops
    # card (static note -> bumps `updated`, no per-tick comms spam).
    local n=1 prev=0
    [ -f "$STREAK_FILE" ] && prev=$(cat "$STREAK_FILE" 2>/dev/null)
    [[ "$prev" =~ ^[0-9]+$ ]] || prev=0
    n=$((prev + 1))
    echo "$n" > "$STREAK_FILE"
    if [ "$n" -ge "$ALERT_AFTER" ]; then
        alert_card "failure-streak" \
            "kanban-commit failed $ALERT_AFTER+ consecutive ticks — last: $1"
    fi
}

reset_tick() {
    # Clean tick: drop the counter; if the ended streak had alerted, leave
    # a recovery comms line on the alert card (committed locally, rides
    # the next tick's push — the served board reads local state anyway).
    local n=0
    [ -f "$STREAK_FILE" ] && n=$(cat "$STREAK_FILE" 2>/dev/null)
    [[ "$n" =~ ^[0-9]+$ ]] || n=0
    rm -f "$STREAK_FILE"
    [ "$n" -ge "$ALERT_AFTER" ] || return 0
    RECOVER_N="$n" python3 - "$REPO" "$ALERT_CARD_ID" <<'PY'
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

repo, cid = Path(sys.argv[1]), sys.argv[2]
n = os.environ["RECOVER_N"]
sys.path.insert(0, str(repo / "scripts/board"))
import card_io
card_path = repo / "docs/ssot/kanban/cards" / f"{cid}.yml"
now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
try:
    with open("/tmp/board-api.lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        card = yaml.safe_load(card_path.read_text()) \
            if card_path.exists() else {}
        if not isinstance(card, dict):
            card = {}
        comms = card.get("comms")
        if not isinstance(comms, list):
            card["comms"] = comms = []
        comms.append(
            {"at": now, "from": "chaba",
             "text": f"recovered after {n} consecutive failed ticks"})
        card.update(id=cid, updated=now)
        card_io.atomic_dump_card(card_path, card)
    render = repo / "scripts/render-board.py"
    if render.exists():
        subprocess.run([sys.executable, str(render)], cwd=repo,
                       check=False, timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception as e:  # recovery note must never crash the loop
    print(f"kanban-commit: recovery note failed: {e}", file=sys.stderr)
PY
    git add -- "docs/ssot/kanban/cards/${ALERT_CARD_ID}.yml" 2>/dev/null \
      && git -c user.name="kanban-bot" \
             -c user.email="kanban-bot@chaba.local" \
             commit --no-verify -qm \
             "board: kanban-commit recovered" \
             -- "docs/ssot/kanban/cards/${ALERT_CARD_ID}.yml" 2>/dev/null \
      || true
}

# Phantom rebase-state guard (OPS-0088): a git-safe-pull killed mid-setup
# can leave .git/rebase-merge holding only `autostash` — git reports
# "rebasing" forever and this check would refuse every tick. A real
# rebase-merge always has onto/head-name, a real rebase-apply always has
# next/last; a dir with none of those never started. Move it aside so the
# tick self-heals instead of wedging the writer.
for _st in rebase-merge rebase-apply; do
    if [ -d "$gitdir/$_st" ] \
       && [ ! -f "$gitdir/$_st/onto" ] \
       && [ ! -f "$gitdir/$_st/head-name" ] \
       && [ ! -f "$gitdir/$_st/next" ] \
       && [ ! -f "$gitdir/$_st/last" ]; then
        mv "$gitdir/$_st" "$gitdir/${_st}.phantom-$(date +%Y%m%d-%H%M%S)" \
          && echo "kanban-commit: cleared phantom $_st state" >&2
    fi
done

if [ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ] || \
   [ -f "$gitdir/MERGE_HEAD" ] || [ -f "$gitdir/CHERRY_PICK_HEAD" ]; then
    echo "kanban-commit: REFUSING to commit — rebase/merge/cherry-pick in progress ($gitdir)" >&2
    alert_card "rebase-in-progress" \
        "rebase/merge/cherry-pick in progress in $REPO — kanban-commit holding until resolved"
    fail_tick "rebase/merge/cherry-pick in progress"
    exit 1
fi

# index.lock stale recovery (card idc03-writer-hardening-index-lock-race):
# a git killed mid-add/commit leaves .git/index.lock behind; every later
# index write then fails "Unable to create index.lock" until someone
# removes it by hand — and the add loop below swallows that failure, so
# the sweep stalled silently (live board edits never committed). git does
# NOT record a holder pid in index.lock (verified empty on git 2.53), so
# staleness is decided by: a pid token in the file or an fuser-visible
# holder that is DEAD, or mtime older than KANBAN_INDEX_LOCK_STALE_S
# (default 900s = 15 min — far longer than any legit index write, short
# enough to self-heal a crash within a tick or two). A fresh lock with a
# live holder is left alone; git_lock_retry's backoff still covers real
# contention. Recovery removes the lock at most once per tick so a
# pathological recreate can't spin.
INDEX_LOCK_STALE_S="${KANBAN_INDEX_LOCK_STALE_S:-900}"
INDEX_LOCK_RECOVERED=0

_index_lock_mtime() {
    stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null
}

_index_lock_holder_pids() {
    # Pids plausibly holding $1: a bare-pid first line when a writer
    # recorded one, plus fuser-visible openers (psmisc; absent -> the
    # age check alone decides).
    local lock="$1" out="" tok p
    tok=$(head -n1 "$lock" 2>/dev/null | tr -d '[:space:]')
    case "$tok" in ''|*[!0-9]*) ;; *) out="$tok";; esac
    if command -v fuser >/dev/null 2>&1; then
        for p in $(fuser "$lock" 2>/dev/null); do
            case " $out " in *" $p "*) ;; *) out="${out:+$out }$p";; esac
        done
    fi
    printf '%s\n' $out
}

index_lock_stale() {
    # rc 0 = stale (dead holder pid, or older than INDEX_LOCK_STALE_S);
    # rc 1 = fresh / live / undecidable — leave it alone.
    local lock="$gitdir/index.lock" now mt p saw=0 alive=0
    [ -f "$lock" ] || return 1
    now=$(date +%s)
    mt=$(_index_lock_mtime "$lock")
    [[ "$mt" =~ ^[0-9]+$ ]] || return 1
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        saw=1
        if [ -d "/proc/$p" ] || kill -0 "$p" 2>/dev/null; then
            alive=1
        fi
    done <<< "$(_index_lock_holder_pids "$lock")"
    [ "$saw" -eq 1 ] && [ "$alive" -eq 0 ] && return 0
    [ $((now - mt)) -gt "$INDEX_LOCK_STALE_S" ]
}

recover_stale_index_lock() {
    # One-shot per tick: clear .git/index.lock iff stale. rc 0 = removed.
    local lock="$gitdir/index.lock" mt now
    [ "$INDEX_LOCK_RECOVERED" -eq 0 ] || return 1
    [ -f "$lock" ] || return 1
    index_lock_stale || return 1
    mt=$(_index_lock_mtime "$lock"); now=$(date +%s)
    rm -f "$lock" || return 1
    INDEX_LOCK_RECOVERED=1
    echo "kanban-commit: cleared stale index.lock (age $((now - ${mt:-now}))s, holder dead or absent)" >&2
    return 0
}

# index.lock contention: board-api's post-lock commit worker runs git
# add/commit per card-write batch while this sweep does bulk add+commit
# — the loser sees "Unable to create index.lock". board-api treats its
# commit as best-effort (deferred retry); this sweep is the durability
# path, so retry briefly instead of failing the whole tick (2026-11-17:
# repeated tick failures while the 2179-commit backlog pushed). A stale
# lock (dead holder / >N min old) is cleared once per tick first.
git_lock_retry() {
    local attempt=0 out
    while [ $attempt -lt 8 ]; do
        out="$("$@" 2>&1)"; rc=$?
        if [ $rc -eq 0 ]; then printf '%s' "$out"; return 0; fi
        case "$out" in
            *index.lock*|*"Another git process"*)
                recover_stale_index_lock || true
                attempt=$((attempt + 1)); sleep $((attempt % 3 + 1));;
            *) printf '%s' "$out" >&2; return $rc;;
        esac
    done
    printf '%s' "$out" >&2
    return 1
}

# Up-front sweep: a stale index.lock would otherwise only surface inside
# the first `git add` below (whose failure is swallowed by `|| true`) —
# clear it now so this tick commits normally. Live locks are untouched.
recover_stale_index_lock || true

for d in docs/ssot/kanban/ docs/ssot/focus-inbox/ stacks/web/public/apps/board/ docs/reports/education-maintenance/ docs/reports/lesson-audit/; do
    [ -d "$d" ] && git_lock_retry git add "$d" ":(exclude)${PROTECTED_PATH}" >/dev/null 2>&1 || true
done

# git errors on a positive pathspec that matches nothing (idc03 20:30:
# "error: pathspec 'stacks/web/public/apps/board/' did not match any file(s)
# known to git" killed the sweep after the guard landed). An empty generated
# dir is normal in a writer checkout, so keep only paths git knows about —
# computed AFTER the `git add` loop so freshly staged files count too.
# Use --error-unmatch, NOT `git ls-files … | grep -q`: under `set -o pipefail`
# grep -q closes the pipe early on a large path (docs/ssot/ has thousands of
# files), git dies of SIGPIPE (141) and the whole `if` reads as false — the
# path silently drops out of COMMIT_PATHS and its staged edits never commit.
COMMIT_PATHS=()
for _p in "${GENERATED_PATHS[@]}"; do
    if git ls-files --error-unmatch "$_p" >/dev/null 2>&1; then
        COMMIT_PATHS+=("$_p")
    fi
done
# A magical exclude pathspec is safe even when the path is absent.
COMMIT_PATHS+=(":(exclude)${PROTECTED_PATH}")

# Stale-write guard (4af10b4c5c, 56aac6476c): the sweep must not commit
# files it does not own, even if another producer or a stale autostash put
# them in the index. `git commit` used to have no pathspec, so any staged
# scripts/ file or a stale docs/ssot/kanban/ssot.kanban.yml was swept into
# "board: live card updates" and reverted newer origin/master content.
# Refuse and surface it on the ops card instead of silently undoing work.
staged_files=$(git diff --cached --name-only --diff-filter=ACMD)
bad_scope=""
bad_prose=""
while IFS= read -r p; do
    [ -z "$p" ] && continue
    if [ "$p" = "$PROTECTED_PATH" ]; then
        bad_prose="$p"
        continue
    fi
    owned=0
    for g in "${GENERATED_PATHS[@]}"; do
        case "$p" in
            "${g%/}"|"$g"*) owned=1; break ;;
        esac
    done
    [ "$owned" -eq 1 ] || bad_scope="${bad_scope:+${bad_scope} }${p}"
done <<< "$staged_files"
if [ -n "$bad_scope" ] || [ -n "$bad_prose" ]; then
    detail=""
    [ -n "$bad_scope" ] && detail="out-of-scope staged: ${bad_scope}"
    [ -n "$bad_prose" ] && detail="${detail:+${detail}; }stale prose staged: ${bad_prose}"
    detail="${detail} — unstage these in ${REPO}; board commits are held"
    echo "kanban-commit: REFUSING to commit — ${detail}" >&2
    alert_card "stale-write-guard" "$detail"
    fail_tick "stale-write-guard"
    exit 1
fi

if git diff --cached --quiet -- "${COMMIT_PATHS[@]}"; then
    rm -f "$STREAK_FILE"   # healthy tick, nothing pending — silent reset
    exit 0
fi

check=$(git diff --cached --check)
if printf '%s\n' "$check" | grep -q 'conflict marker'; then
    hits=$(printf '%s\n' "$check" | grep 'conflict marker')
    echo "kanban-commit: REFUSING to commit — conflict markers staged:" >&2
    printf '%s\n' "$hits" >&2
    files=$(printf '%s\n' "$hits" | cut -d: -f1 | sort -u | paste -sd, -)
    alert_card "conflict-markers" "conflict markers staged in: $files"
    fail_tick "conflict markers staged"
    exit 1
fi

# YAML syntax guard (card guard-card-yaml-syntax-validation-at-wri):
# conflict-marker check above only catches <<<< shapes — a malformed card
# without markers (hand edit, bad board-api write, broken merge resolution)
# would commit fine here and then kill render-board + kanban-dispatch on
# parse for everyone downstream (2026-10-11: board stale 2.5h). Refuse
# instead; the alert card names the files so the wedge is never silent.
yml_bad=$(python3 - <<'PY'
import subprocess
import yaml

out = subprocess.run(
    ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACM"],
    capture_output=True, text=True).stdout
for f in out.split("\0"):
    if not f.endswith(".yml"):
        continue
    try:
        yaml.safe_load(open(f, encoding="utf-8"))
    except Exception as e:
        mark = getattr(e, "problem_mark", None)
        loc = f":{mark.line + 1}:{mark.column + 1}" if mark else ""
        print(f"{f}{loc}: {getattr(e, 'problem', None) or str(e)[:100]}")
PY
)
if [ -n "$yml_bad" ]; then
    echo "kanban-commit: REFUSING to commit — YAML syntax errors staged:" >&2
    printf '%s\n' "$yml_bad" >&2
    files=$(printf '%s\n' "$yml_bad" | cut -d: -f1 | sort -u | paste -sd, -)
    alert_card "yaml-syntax" "unparseable YAML staged in: $files"
    fail_tick "unparseable YAML staged"
    exit 1
fi

git_lock_retry git -c user.name="kanban-bot" -c user.email="kanban-bot@chaba.local" \
    commit -qm "board: live card updates ($(date '+%F %H:%M'))" \
    -- "${COMMIT_PATHS[@]}" \
    || { fail_tick "commit failed"; exit 1; }

attempt=0
while [ $attempt -lt "$PUSH_RETRIES" ]; do
    attempt=$((attempt + 1))
    pre_pull_head="$(git rev-parse HEAD 2>/dev/null || true)"
    if ! SAFE_PULL_GENERATED_RE="$GENERATED_RE" bash "$SAFE_PULL" "$REPO"; then
        echo "kanban-commit: pull needs manual resolution — next tick retries" >&2
        fail_tick "pull needs manual resolution"
        exit 1
    fi
    # Self-restart when a pull lands new service code — the long-running
    # unit otherwise keeps serving the pre-merge implementation until
    # somebody notices (2026-11-07: board-api served 14-min-stale code
    # across a merge, OPS-1107). try-restart is a no-op where the unit
    # isn't running.
    if [ -n "$pre_pull_head" ] \
        && [ "$pre_pull_head" != "$(git rev-parse HEAD 2>/dev/null)" ] \
        && ! git diff --quiet "$pre_pull_head" HEAD \
            -- scripts/board/board-api.py; then
        systemctl --user try-restart chaba-board-api.service 2>/dev/null \
            && echo "kanban-commit: board-api.py changed in pull — restarted chaba-board-api" \
            || true
    fi
    push_log="$(git push origin master 2>&1)"; rc=$?
    [ -n "$push_log" ] && echo "$push_log" | tail -2
    if [ $rc -eq 0 ]; then
        reset_tick
        exit 0
    fi
    [ $attempt -lt "$PUSH_RETRIES" ] && sleep $((RANDOM % 8 + 2))
done
echo "kanban-commit: push failed after $PUSH_RETRIES attempts" >&2
fail_tick "push failed after $PUSH_RETRIES attempts"
exit 1
