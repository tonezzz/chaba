#!/usr/bin/env bash
# devin-dispatch — launch/track headless Devin CLI sessions on this host.
#
# Ada calls this over ssh (devin_dispatch tool). Each task gets a dedicated
# git worktree (AGENTS.md parallel-session rule) and a systemd --user unit
# so it survives ssh disconnects and is inspectable via systemctl/journalctl.
#
# Usage:
#   devin-dispatch start <repo> "<task>"     launch session, prints task id
#   devin-dispatch status [id]               list tasks / show one
#   devin-dispatch followup <id> "<msg>"     resume the session with a message
#   devin-dispatch resume <sid> ["<msg>"]    continue a STALE session (any
#                                          desktop/CLI session in sessions.db)
#                                          headlessly in its recorded cwd —
#                                          no worktree, wrap-up/research only
#   devin-dispatch logs <id>                 journal for the task's unit(s)
#   devin-dispatch tail <id>                 tail the exported transcript
#
# Repos are whitelisted below — add a name=path pair to allow more.
# Env: DISPATCH_PERMISSION_MODE (default smart), DISPATCH_DIR, DEVIN_BIN.
#
# Permission modes (devin --help): auto = read-only only, accept-edits =
# +workspace edits, smart = +model-judged actions, dangerous = all tools.
# For real build tasks use DISPATCH_PERMISSION_MODE=dangerous — 'smart'
# auto-rejects anything the fast model deems risky (curl/pytest/systemctl)
# and an unattended session just quits on rejection (seen 2026-09-23:
# doc-archive task died after two rejections). Worktree isolation +
# the no-push/no-deploy prompt rails are the real guardrails.
#
# Gotcha: worktrees are cut from THIS host's local HEAD — files committed
# on another host won't exist in the worktree until tony-dell pulls.
# Copy spec inputs into the worktree explicitly if they're unpushed.

set -euo pipefail

DEVIN_BIN="${DEVIN_BIN:-$(command -v devin || echo /usr/share/devin-desktop/resources/app/extensions/windsurf/devin/bin/devin)}"
DISPATCH_DIR="${DISPATCH_DIR:-$HOME/.local/share/devin-dispatch}"
PERMISSION_MODE="${DISPATCH_PERMISSION_MODE:-smart}"

declare -A REPOS=(
  [chaba]="$HOME/CascadeProjects/chaba"
  [ada-pi]="$HOME/CascadeProjects/ada-pi"
  [sunsynk-card]="$HOME/CascadeProjects/sunsynk-power-flow-card"
)

_slug() { tr '[:upper:]' '[:lower:]' <<<"$1" | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//' | cut -c1-30; }

# job/<id> doc in the devin-handoff bank — the shared job ledger Ada's
# devin_pending and the Report tab's dispatch layer read. Best-effort.
mddb_job() { # id status summary question
  local id="$1" st="$2" summ="${3:-}" q="${4:-}"
  ID="$id" ST="$st" SUMM="$summ" Q="$q" HOSTN="$(hostname)" python3 - <<'PY' \
    | curl -sf -m 15 -X POST -H "Content-Type: application/json" -d @- \
      "${MDDB_URL:-http://100.74.146.0:11023/v1}/add" >/dev/null 2>&1
import json, os
from datetime import datetime, timezone
meta = {"kind": ["job"], "status": [os.environ["ST"]],
        "job_id": [os.environ["ID"]], "host": [os.environ["HOSTN"]],
        "ts": [datetime.now(timezone.utc).isoformat()],
        "subject": ["job-" + os.environ["ID"]],
        "source": ["devin-dispatch"], "written_by": ["devin-dispatch"],
        "scope": ["tony"], "bank": ["devin-handoff"]}
if os.environ.get("Q"):
    meta["question"] = [os.environ["Q"]]
body = f"Job {os.environ['ID']} on {os.environ['HOSTN']}: {os.environ['ST']}."
if os.environ.get("Q"):
    body += f"\n\nNeeds input: {os.environ['Q']}"
if os.environ.get("SUMM"):
    body += f"\n\n{os.environ['SUMM']}"
print(json.dumps({"collection": "ada-ha-bank-devin-handoff",
                  "key": "job/" + os.environ["ID"], "lang": "en",
                  "contentMd": body, "meta": meta}))
PY
  return 0
}

_meta_get() { python3 -c "import json,sys;print(json.load(open('$1')).get('$2') or '')"; }

_meta_write() { # dir repo worktree branch unit
  python3 - "$1" "$2" "$3" "$4" "$5" <<'PY'
import json, sys
from datetime import datetime, timezone
d, repo, wt, branch, unit = sys.argv[1:6]
meta = {"repo": repo, "worktree": wt, "branch": branch, "unit": unit,
        "permission_mode": "see prompt", "started_at": datetime.now(timezone.utc).isoformat()}
json.dump(meta, open(f"{d}/meta.json", "w"), indent=1)
PY
}

_devin_run() { # unit worktree prompt_file extra-args...
  local unit="$1" wt="$2" prompt="$3"; shift 3
  # No positional PATH arg: --print mode rejects it; --working-directory
  # already sets the session workspace.
  # The unit runs under --collect: when it finishes, systemd unloads it and
  # the Result field is gone (user journal doesn't retain Succeeded/Failed
  # lines here). Wrap the run so the real exit code lands in the task dir —
  # devin-dispatch-watch reads it to report the true outcome.
  systemd-run --user --unit="$unit" --working-directory="$wt" --collect \
    --setenv=HOME="$HOME" --setenv=PATH="$PATH" \
    --setenv=DEVIN_BIN="$DEVIN_BIN" --setenv=PERMISSION_MODE="$PERMISSION_MODE" \
    --setenv=PROMPT="$prompt" --setenv=TASK_DIR="$(dirname "$prompt")" \
    /bin/bash -c 'rc=0; "$DEVIN_BIN" -p --permission-mode "$PERMISSION_MODE" \
      --respect-workspace-trust false --prompt-file "$PROMPT" "$@" || rc=$?; \
      echo "$rc" > "$TASK_DIR/exit_code"; exit "$rc"' _ "$@"
}

cmd_start() {
  local repo="${1:?repo required}"; shift
  local task="$*"
  [[ -n $task ]] || { echo "usage: devin-dispatch start <repo> \"<task>\"" >&2; exit 2; }
  local root="${REPOS[$repo]:-}"
  [[ -n $root && -d $root ]] || { echo "unknown repo '$repo' (allowed: ${!REPOS[*]})" >&2; exit 1; }
  local id="$(date +%Y%m%d-%H%M%S)-$(_slug "$task")"
  local wt="$HOME/CascadeProjects/dispatch-wt-$id"
  local dir="$DISPATCH_DIR/tasks/$id"
  mkdir -p "$dir"
  git -C "$root" worktree add "$wt" -b "dispatch/$id" >/dev/null 2>&1 || {
    echo "worktree failed for $root" >&2; exit 1; }
  cat > "$dir/prompt.txt" <<EOF
You are running unattended via devin-dispatch (a headless, user-triggered
session). Work only inside this worktree. Do not commit to the default
branch, do not push, and do not deploy unless the task explicitly says so.
When finished, end with a short summary of what changed and how to verify it.
If you are blocked and need a decision from the user, write your question to
\$TASK_DIR/needs-input.txt (first line: one-line question, then context) and
stop — the operator is notified and can resume you with an answer.
If the work produces a decision, runbook, or new infra, write it to
docs/ssot/jobs/<domain>/<date>-<slug>.yml or reports/ before ending —
leave a trail.

Task: $task
EOF
  _devin_run "devin-task-$id" "$wt" "$dir/prompt.txt" \
    --export "$dir/transcript.json"
  _meta_write "$dir" "$repo" "$wt" "dispatch/$id" "devin-task-$id"
  mddb_job "$id" "running" "$task" &
  echo "$id"
}

cmd_status() {
  local only="${1:-}"
  local d id unit state result ts repo
  for d in "$DISPATCH_DIR"/tasks/*/; do
    [[ -d $d ]] || continue
    id=$(basename "$d")
    [[ -n $only && $id != "$only" ]] && continue
    unit="devin-task-$id"
    state=$(systemctl --user show "$unit" -p ActiveState --value 2>/dev/null || true)
    result=$(systemctl --user show "$unit" -p Result --value 2>/dev/null || true)
    repo=$(_meta_get "$d/meta.json" repo 2>/dev/null || true)
    ts=$(stat -c %y "$d/transcript.json" 2>/dev/null | cut -d. -f1 || true)
    printf '%-42s %-8s %-10s repo=%-14s transcript=%s\n' \
      "$id" "${state:-gone}" "${result:--}" "${repo:-?}" "${ts:-never}"
  done
}

cmd_followup() {
  local id="${1:?id required}"; shift
  local msg="$*"
  [[ -n $msg ]] || { echo "usage: devin-dispatch followup <id> \"<msg>\"" >&2; exit 2; }
  local d="$DISPATCH_DIR/tasks/$id" wt n
  [[ -d $d ]] || { echo "no task $id" >&2; exit 1; }
  wt=$(_meta_get "$d/meta.json" worktree)
  # A follow-up answers the pending question — clear the marker so the watch
  # reports the next completion on its own terms.
  rm -f "$d/needs-input.txt"
  n=$(( $(find "$d" -name 'fu-*.txt' | wc -l) + 1 ))
  printf '%s\n' "$msg" > "$d/fu-$n.txt"
  _devin_run "devin-task-$id-fu$n" "$wt" "$d/fu-$n.txt" \
    -c --export "$d/transcript.json"
  echo "followup $n sent to $id"
}

# resume <session-id> ["<message>"] — continue an EXISTING (e.g. stale
# desktop) session headlessly in its recorded working dir. No worktree —
# for wrap-up/research sessions only; code work should be redispatched
# with `start`. Same unit/transcript/registry pipeline as start, so the
# watch timer + job/<id> ledger pick it up automatically.
cmd_resume() {
    local sid="${1:?session-id}" msg="${2:-Continue where you left off and finish any pending work. Summarize what was completed.}"
    local db="${DEVIN_SESSIONS_DB:-$HOME/.local/share/devin/cli/sessions.db}"
    local cwd title
    read -r cwd title < <(SESSION="$sid" DB="$db" python3 - <<'PY'
import sqlite3, os
c = sqlite3.connect("file:%s?mode=ro" % os.environ["DB"], uri=True)
row = c.execute("select working_directory, title from sessions where id=?",
                (os.environ["SESSION"],)).fetchone()
if row:
    print((row[0] or os.path.expanduser("~")), (row[1] or "session")[:80])
PY
)
    [[ -d ${cwd:-/nonexistent} ]] || { echo "no session/cwd for $sid" >&2; exit 1; }
    local id
    id="resume-$(date +%Y%m%d-%H%M%S)-$(_slug "$title")"
    local dir="$DISPATCH_DIR/tasks/$id"
    mkdir -p "$dir"
    cat > "$dir/prompt.txt" <<EOF
You are resuming a session via devin-dispatch (headless, user-triggered).
Do not commit to the default branch, do not push, and do not deploy unless
the task explicitly says so.
If you are blocked and need a decision from the user, write your question to
\$TASK_DIR/needs-input.txt (first line: one-line question, then context) and
stop — the operator is notified and can resume you with an answer.
If the work produces a decision, runbook, or new infra, write it to
docs/ssot/jobs/<domain>/<date>-<slug>.yml or reports/ before ending —
leave a trail.

$msg
EOF
    _devin_run "devin-task-$id" "$cwd" "$dir/prompt.txt" \
        --export "$dir/transcript.json" -r "$sid"
    _meta_write "$dir" "resume" "$cwd" "resume/$sid" "devin-task-$id"
    mddb_job "$id" "running" "resume: $title" &
    echo "$id"
}

cmd_logs() { journalctl --user -u "devin-task-${1:?id required}*" --no-pager "${@:2}"; }
cmd_tail() { tail -n "${2:-40}" "$DISPATCH_DIR/tasks/${1:?id required}/transcript.json"; }

case "${1:-}" in
  start)    shift; cmd_start "$@" ;;
  status)   shift; cmd_status "$@" ;;
  followup) shift; cmd_followup "$@" ;;
  resume)   shift; cmd_resume "$@" ;;
  logs)     shift; cmd_logs "$@" ;;
  tail)     shift; cmd_tail "$@" ;;
  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
