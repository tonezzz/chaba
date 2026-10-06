#!/usr/bin/env bash
# devin-dispatch-prune — prune merged dispatch/* branches and their
# dispatch-wt-* worktrees. Runs weekly from devin-dispatch-prune.timer.
#
# For every repo in the dispatch whitelist ($DISPATCH_DIR/repos.conf —
# the same table devin-dispatch reads; built-in fallback below) each
# local dispatch/* branch is ancestry-checked against origin/<default>:
#
#   git merge-base --is-ancestor dispatch/<id> origin/<default>
#
# A merged branch is deleted with `git branch -d` (never -D). When a
# worktree has the branch checked out, the worktree is removed first
# with `git worktree remove` (never --force). A worktree is only removed
# when ALL of these hold — the same guard semantics as
# devin-precleanup-check.py:
#   * git status --porcelain is empty (clean tree)
#   * the worktree is not locked (git worktree lock)
#   * no devin-task-<id>* unit is active/activating for it
#     (the task registry meta.worktree and the dispatch-wt-<id> name
#      are both checked)
# If any guard fails, BOTH the worktree and the branch are left alone —
# a checked-out branch cannot be safely deleted anyway.
#
# Orphan case: a dispatch-wt-* worktree whose branch is already gone
# shows up 'detached' in `git worktree list`; it is removed only when
# its HEAD is an ancestor of origin/<default> and the same guards pass.
#
# Usage:
#   devin-dispatch-prune [--dry-run] [-v]
#
# Env:
#   DISPATCH_DIR   task registry + repos.conf (default ~/.local/share/devin-dispatch)
#   REPOS_CONF     override repos.conf path (testing)
#   WT_GLOB        worktree dir glob (default $HOME/CascadeProjects/dispatch-wt-*)
#   PRUNE_EVENT=0  skip the chaba-admin event emit
#
# Install: scripts/devin/devin-dispatch-prune.sh -> ~/.local/bin/devin-dispatch-prune
#          systemd/devin-dispatch-prune.{service,timer} -> ~/.config/systemd/user/
set -uo pipefail

DRY_RUN=0
VERBOSE=0
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY_RUN=1 ;;
        -v|--verbose) VERBOSE=1 ;;
        -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

DISPATCH_DIR="${DISPATCH_DIR:-$HOME/.local/share/devin-dispatch}"
REPOS_CONF="${REPOS_CONF:-$DISPATCH_DIR/repos.conf}"
WT_GLOB="${WT_GLOB:-$HOME/CascadeProjects/dispatch-wt-*}"
EVENT_LOG="$HOME/.config/home-assistant/scripts/chaba-event-log.py"

log() { echo "$(date -Iseconds) $*"; }
vlog() { [ "$VERBOSE" = 1 ] && log "$@" || true; }

# --- repo whitelist (name path default_branch) — mirrors devin-dispatch.sh
declare -A REPOS REPO_DEFAULT_BRANCH
_load_repos() {
    if [[ -f $REPOS_CONF ]]; then
        local name path branch
        while read -r name path branch _; do
            [[ -n ${name:-} && $name != \#* && -n ${path:-} ]] || continue
            [[ ${branch:-} == \#* ]] && branch=""
            REPOS[$name]="$path"
            REPO_DEFAULT_BRANCH[$name]="${branch:-master}"
        done < "$REPOS_CONF"
    else
        REPOS=(
            [chaba]="$HOME/CascadeProjects/chaba"
            [ada-pi]="$HOME/CascadeProjects/ada-pi"
            [sunsynk-card]="$HOME/CascadeProjects/sunsynk-power-flow-card"
            [mddb-fork]="$HOME/CascadeProjects/mddb-fork"
        )
        REPO_DEFAULT_BRANCH=(
            [chaba]="master" [ada-pi]="main"
            [sunsynk-card]="main" [mddb-fork]="main"
        )
    fi
}
_load_repos

# --- protected worktrees --------------------------------------------------
# A worktree is protected when any devin-task-* unit bound to it is still
# active/activating. Protection is resolved two ways:
#   1. name-derived: dispatch-wt-<id> -> devin-task-<id>* units
#   2. registry:     tasks/<id>/meta.json worktree == path
declare -A PROTECTED_WT
_collect_protected() {
    local units id d wt
    units=$(systemctl --user list-units --state=active,activating --no-legend \
            'devin-task-*' 2>/dev/null | awk '{print $1}' | sed 's/\.service$//')
    for u in $units; do
        id="${u#devin-task-}"
        id="${id%%-fu[0-9]*}"   # strip follow-up suffix -> base task id
        # name-derived
        PROTECTED_WT["$HOME/CascadeProjects/dispatch-wt-$id"]=1
        # registry-derived
        d="$DISPATCH_DIR/tasks/$id"
        if [ -f "$d/meta.json" ]; then
            wt=$(python3 -c "import json;print(json.load(open('$d/meta.json')).get('worktree') or '')" 2>/dev/null)
            [ -n "$wt" ] && PROTECTED_WT["$wt"]=1
        fi
    done
}
_collect_protected

# --- per-repo worktree map -------------------------------------------------
# Fills:  WT_OF_BRANCH[branch]=path   LOCKED_WT[path]=1
#         DETACHED_WT[path]=head-sha  (dispatch-wt-* only)
declare -A WT_OF_BRANCH LOCKED_WT DETACHED_WT
_map_worktrees() { # repo
    WT_OF_BRANCH=(); LOCKED_WT=(); DETACHED_WT=()
    local repo="$1" wt="" branch="" head="" detached=0
    while IFS= read -r line; do
        case "$line" in
            "worktree "*) wt="${line#worktree }"; branch=""; head=""; detached=0 ;;
            "HEAD "*)     head="${line#HEAD }" ;;
            "branch refs/heads/"*) branch="${line#branch refs/heads/}" ;;
            "detached")   detached=1 ;;
            "locked"*)    [ -n "$wt" ] && LOCKED_WT["$wt"]=1 ;;
            "")
                [ -n "$wt" ] || continue
                if [ -n "$branch" ]; then
                    WT_OF_BRANCH["$branch"]="$wt"
                elif [ "$detached" = 1 ]; then
                    case "$wt" in
                        $WT_GLOB) DETACHED_WT["$wt"]="$head" ;;
                    esac
                fi
                wt=""; branch=""; head=""; detached=0
                ;;
        esac
    done < <(git -C "$repo" worktree list --porcelain 2>/dev/null)
    # trailing record (porcelain output may not end with a blank line)
    if [ -n "$wt" ]; then
        if [ -n "$branch" ]; then WT_OF_BRANCH["$branch"]="$wt"
        elif [ "$detached" = 1 ]; then
            case "$wt" in $WT_GLOB) DETACHED_WT["$wt"]="$head" ;; esac
        fi
    fi
}

wt_dirty() { # path -> 0 when dirty or unreadable (fail-safe: treat as dirty)
    local out
    out=$(git -C "$1" status --porcelain=v1 2>/dev/null) || return 0
    [ -n "$out" ]
}

merged() { # repo ref base -> 0 when ref is ancestor of base
    git -C "$1" merge-base --is-ancestor "$2" "$3" 2>/dev/null
}

wt_remove() { # repo path
    if [ "$DRY_RUN" = 1 ]; then return 0; fi
    git -C "$1" worktree remove "$2" >/dev/null 2>&1
}

branch_delete() { # repo branch base
    if [ "$DRY_RUN" = 1 ]; then return 0; fi
    git -C "$1" branch -d "$2" >/dev/null 2>&1 && return 0
    # -d can refuse when the branch has no upstream and the checkout's HEAD
    # does not contain it, even though origin/<default> does (the real gate
    # above already proved ancestry). Re-verify the gate, then force-delete;
    # -D still refuses when the branch is checked out in a worktree.
    git -C "$1" merge-base --is-ancestor "$2" "$3" 2>/dev/null \
        && git -C "$1" branch -D "$2" >/dev/null 2>&1
}

# --- emit a single chaba-admin event (best-effort, never fatal) ------------
emit_event() { # title severity body
    [ "${PRUNE_EVENT:-1}" = "1" ] || return 0
    local payload
    payload=$(TITLE="$1" SEV="$2" BODY="$3" python3 - <<'PY' 2>/dev/null
import json, os
print(json.dumps({"title": os.environ["TITLE"], "category": "devin-dispatch",
    "source": "devin-dispatch-prune", "severity": os.environ["SEV"],
    "requires_response": False, "body": os.environ["BODY"]}))
PY
)
    [ -n "$payload" ] || return 0
    if [ -f "$EVENT_LOG" ]; then
        printf '%s\n' "$payload" | python3 "$EVENT_LOG" add - >/dev/null 2>&1 && return 0
    fi
    printf '%s\n' "$payload" | ssh -o BatchMode=yes -o ConnectTimeout=8 \
        "${EVENT_SSH:-tony-dell-lan}" \
        "python3 ~/.config/home-assistant/scripts/chaba-event-log.py add -" \
        >/dev/null 2>&1 || true
    return 0
}

# --- main ------------------------------------------------------------------
[ "$DRY_RUN" = 1 ] && log "DRY-RUN — no deletions will be made"
pruned_branches=0 pruned_wts=0 kept=0 failed=0 skipped_repos=0
declare -a PRUNED_KEPT_LINES

for repo_name in "${!REPOS[@]}"; do
    repo="${REPOS[$repo_name]}"
    dbranch="${REPO_DEFAULT_BRANCH[$repo_name]:-master}"
    [ -d "$repo" ] || { log "skip $repo_name: $repo missing"; skipped_repos=$((skipped_repos+1)); continue; }
    [ -d "$repo/.git" ] || git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 \
        || { log "skip $repo_name: $repo not a git repo"; skipped_repos=$((skipped_repos+1)); continue; }

    # Fresh origin ref so 'merged' reflects the real remote state; fall back
    # to the last-fetched ref when the network is down (never to a local
    # branch — a checkout parked sideways must not define 'merged').
    git -C "$repo" fetch -q origin "$dbranch" >/dev/null 2>&1 \
        || vlog "$repo_name: fetch origin/$dbranch failed — using last-fetched ref"
    base="origin/$dbranch"
    git -C "$repo" rev-parse --verify --quiet "$base" >/dev/null || {
        log "skip $repo_name: no $base ref"; skipped_repos=$((skipped_repos+1)); continue; }

    _map_worktrees "$repo"

    while IFS= read -r branch; do
        [ -n "$branch" ] || continue
        if ! merged "$repo" "$branch" "$base"; then
            vlog "keep $repo_name:$branch — not merged into $base"
            kept=$((kept+1)); PRUNED_KEPT_LINES+=("keep $repo_name:$branch (unmerged)")
            continue
        fi
        wt="${WT_OF_BRANCH[$branch]:-}"
        if [ -n "$wt" ]; then
            if [ -n "${LOCKED_WT[$wt]:-}" ]; then
                log "keep $repo_name:$branch — worktree $wt is locked"
                kept=$((kept+1)); continue
            fi
            if [ -n "${PROTECTED_WT[$wt]:-}" ]; then
                log "keep $repo_name:$branch — worktree $wt has an active devin-task unit"
                kept=$((kept+1)); continue
            fi
            if wt_dirty "$wt"; then
                log "keep $repo_name:$branch — worktree $wt is dirty"
                kept=$((kept+1)); continue
            fi
            if wt_remove "$repo" "$wt"; then
                log "prune $repo_name: worktree $wt $([ "$DRY_RUN" = 1 ] && echo 'would be removed' || echo 'removed') (clean, merged)"
                pruned_wts=$((pruned_wts+1))
            else
                log "FAIL $repo_name: git worktree remove $wt"
                failed=$((failed+1)); continue   # leave the branch — still checked out
            fi
        fi
        if branch_delete "$repo" "$branch" "$base"; then
            log "prune $repo_name: branch $branch $([ "$DRY_RUN" = 1 ] && echo 'would be deleted' || echo 'deleted') (merged into $base)"
            pruned_branches=$((pruned_branches+1))
        else
            log "FAIL $repo_name: git branch -d $branch"
            failed=$((failed+1))
        fi
    done < <(git -C "$repo" for-each-ref --format='%(refname:short)' 'refs/heads/dispatch/')

    # Orphaned dispatch worktrees: branch already gone, HEAD detached.
    for wt in "${!DETACHED_WT[@]}"; do
        [ -d "$wt" ] || continue
        if ! merged "$repo" "${DETACHED_WT[$wt]}" "$base"; then
            vlog "keep $repo_name:$wt — detached HEAD not merged into $base"
            kept=$((kept+1)); continue
        fi
        if [ -n "${LOCKED_WT[$wt]:-}" ]; then
            log "keep $repo_name:$wt — detached worktree is locked"
            kept=$((kept+1)); continue
        fi
        if [ -n "${PROTECTED_WT[$wt]:-}" ]; then
            log "keep $repo_name:$wt — active devin-task unit"
            kept=$((kept+1)); continue
        fi
        if wt_dirty "$wt"; then
            log "keep $repo_name:$wt — detached worktree is dirty"
            kept=$((kept+1)); continue
        fi
        if wt_remove "$repo" "$wt"; then
            log "prune $repo_name: detached worktree $wt $([ "$DRY_RUN" = 1 ] && echo 'would be removed' || echo 'removed') (HEAD merged)"
            pruned_wts=$((pruned_wts+1))
        else
            log "FAIL $repo_name: git worktree remove $wt"
            failed=$((failed+1))
        fi
    done

    [ "$DRY_RUN" = 1 ] || git -C "$repo" worktree prune 2>/dev/null || true
done

summary="branches_deleted=$pruned_branches worktrees_removed=$pruned_wts kept=$kept failed=$failed skipped_repos=$skipped_repos dry_run=$DRY_RUN"
log "summary: $summary"

if [ "$pruned_branches" -gt 0 ] || [ "$pruned_wts" -gt 0 ] || [ "$failed" -gt 0 ]; then
    emit_event "devin-dispatch-prune on $(hostname): $summary" \
        "$([ "$failed" -gt 0 ] && echo warn || echo info)" \
        "Weekly merged dispatch/* prune. $summary. See journalctl --user -u devin-dispatch-prune for the per-branch log."
fi

[ "$failed" -gt 0 ] && exit 1
exit 0
