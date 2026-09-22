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
#   devin-dispatch logs <id>                 journal for the task's unit(s)
#   devin-dispatch tail <id>                 tail the exported transcript
#
# Repos are whitelisted below — add a name=path pair to allow more.
# Env: DISPATCH_PERMISSION_MODE (default smart), DISPATCH_DIR, DEVIN_BIN.

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
  systemd-run --user --unit="$unit" --working-directory="$wt" --collect \
    --setenv=HOME="$HOME" --setenv=PATH="$PATH" \
    "$DEVIN_BIN" -p --permission-mode "$PERMISSION_MODE" \
    --respect-workspace-trust false \
    --prompt-file "$prompt" "$@"
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

Task: $task
EOF
  _devin_run "devin-task-$id" "$wt" "$dir/prompt.txt" \
    --export "$dir/transcript.json"
  _meta_write "$dir" "$repo" "$wt" "dispatch/$id" "devin-task-$id"
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
  n=$(( $(find "$d" -name 'fu-*.txt' | wc -l) + 1 ))
  printf '%s\n' "$msg" > "$d/fu-$n.txt"
  _devin_run "devin-task-$id-fu$n" "$wt" "$d/fu-$n.txt" \
    -c --export "$d/transcript.json"
  echo "followup $n sent to $id"
}

cmd_logs() { journalctl --user -u "devin-task-${1:?id required}*" --no-pager "${@:2}"; }
cmd_tail() { tail -n "${2:-40}" "$DISPATCH_DIR/tasks/${1:?id required}/transcript.json"; }

case "${1:-}" in
  start)    shift; cmd_start "$@" ;;
  status)   shift; cmd_status "$@" ;;
  followup) shift; cmd_followup "$@" ;;
  logs)     shift; cmd_logs "$@" ;;
  tail)     shift; cmd_tail "$@" ;;
  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
