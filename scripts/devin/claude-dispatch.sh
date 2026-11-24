#!/usr/bin/env bash
# claude-dispatch — launch/track headless Claude Code sessions on this host.
#
# Sibling of devin-dispatch with the SAME external contract, so the whole
# kanban close-out machinery (runner-agent finish_pass, merge-sweep,
# dispatch-wt-sweep, job/<id> ledger) works unchanged:
#   * task dirs live in the shared $DISPATCH_DIR/tasks/<id>/
#   * units are named devin-task-<id> (merge-sweep/dispatch-wt-sweep glob
#     that prefix — a claude-task-* name would be invisible to them)
#   * worktrees are ~/CascadeProjects/dispatch-wt-<id> on branch
#     dispatch/<id>, cut from origin/<default_branch>
#   * meta.json carries "executor": "claude" so provenance is recorded
#
# Usage:
#   claude-dispatch start <repo> "<task>"   launch session, prints task id
#   claude-dispatch status [id]             list tasks / show one
#   claude-dispatch followup <id> "<msg>"   resume the session with a message
#   claude-dispatch logs <id>               journal for the task's unit(s)
#   claude-dispatch tail <id>               tail the event transcript
#
# Repos are whitelisted in $DISPATCH_DIR/repos.conf — the SAME file
# devin-dispatch reads (name path default_branch per line;
# scripts/devin/dispatch-repos.conf is the versioned copy).
#
# Env:
#   CLAUDE_BIN              claude binary (default: PATH, then
#                           node_modules/.bin under ~/CascadeProjects,
#                           then ~/.local/bin/claude)
#   CLAUDE_CONFIG_DIR       passed through to claude untouched — the host's
#                           normal ~/.claude auth applies. Point elsewhere
#                           only for isolated eval lanes.
#   DISPATCH_MODEL          kanban action.model -> `claude --model`.
#                           Accepted: sonnet|opus|haiku|claude-*. Anything
#                           else (litellm/*, swe-*, junk) falls back to
#                           $CLAUDE_MODEL (default sonnet) — lane-model
#                           ids are devin/litellm names, never claude's.
#   DISPATCH_EFFORT         -> `claude --effort` (low|medium|high|xhigh|max)
#   CLAUDE_PERMISSION_MODE  default bypassPermissions (= --dangerously-
#                           skip-permissions, required unattended). Set e.g.
#                           acceptEdits for a more guarded lane.
#   DISPATCH_UNIT_PROPS     extra systemd-run --property= args (same splice
#                           contract as devin-dispatch; runner-agent's
#                           task_run_props() flows through).
#   DISPATCH_DIR            default ~/.local/share/devin-dispatch (shared).
#
# Eval note (2026-11-18, tony-claude-code-00): sonnet was the best
# tokens-per-verified-fix lane on the runner-dispatch-no-timeout card;
# haiku burned 2x the tokens via more turns; effort=low skipped tests.

set -euo pipefail

CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || true)}"
if [[ -z $CLAUDE_BIN ]]; then
  for c in "$HOME/.local/bin/claude" \
           "$HOME/CascadeProjects/tony-projects/tony-claude-code-00/node_modules/.bin/claude"; do
    [[ -x $c ]] && { CLAUDE_BIN="$c"; break; }
  done
fi
[[ -n $CLAUDE_BIN && -x $CLAUDE_BIN ]] || {
  echo "claude binary not found (set CLAUDE_BIN)" >&2; exit 1; }

DISPATCH_DIR="${DISPATCH_DIR:-$HOME/.local/share/devin-dispatch}"
MODEL="${CLAUDE_MODEL:-sonnet}"
case "${DISPATCH_MODEL:-}" in
  sonnet|opus|haiku|claude-*) MODEL="$DISPATCH_MODEL" ;;
  "") ;;
  *) echo "warn: DISPATCH_MODEL='$DISPATCH_MODEL' is not a claude id — using $MODEL" >&2 ;;
esac
EFFORT="${DISPATCH_EFFORT:-}"
PERMISSION_MODE="${CLAUDE_PERMISSION_MODE:-bypassPermissions}"

# Fallback whitelist — canonical table is $DISPATCH_DIR/repos.conf
# (name path default_branch). Keep both in sync with devin-dispatch.
declare -A REPOS REPO_DEFAULT_BRANCH
_load_repos() {
  local conf="$DISPATCH_DIR/repos.conf"
  if [[ -f $conf ]]; then
    local name path branch
    while read -r name path branch _; do
      [[ -n ${name:-} && $name != \#* && -n ${path:-} ]] || continue
      [[ ${branch:-} == \#* ]] && branch=""
      REPOS[$name]="$path"
      REPO_DEFAULT_BRANCH[$name]="${branch:-master}"
    done < "$conf"
  else
    REPOS=(
      [chaba]="$HOME/CascadeProjects/chaba"
      [ada-voice]="$HOME/CascadeProjects/ada-voice"
      [sunsynk-card]="$HOME/CascadeProjects/sunsynk-power-flow-card"
      [mddb-fork]="$HOME/CascadeProjects/mddb-fork"
    )
    REPO_DEFAULT_BRANCH=(
      [chaba]="master" [ada-voice]="main"
      [sunsynk-card]="main" [mddb-fork]="main"
    )
  fi
}
_load_repos

_slug() { tr '[:upper:]' '[:lower:]' <<<"$1" | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//' | cut -c1-30; }

# job/<id> doc in the devin-handoff bank — the shared job ledger Ada's
# devin_pending and the Report tab's dispatch layer read. Best-effort.
mddb_job() { # id status summary question
  local id="$1" st="$2" summ="${3:-}" q="${4:-}"
  ID="$id" ST="$st" SUMM="$summ" Q="$q" HOSTN="$(hostname)" python3 - <<'PY' \
    | curl -sf -m 15 -X POST -H "Content-Type: application/json" -d @- \
      "${MDDB_URL:-http://100.102.134.91:11023/v1}/add" >/dev/null 2>&1
import json, os
from datetime import datetime, timezone
meta = {"kind": ["job"], "status": [os.environ["ST"]],
        "job_id": [os.environ["ID"]], "host": [os.environ["HOSTN"]],
        "ts": [datetime.now(timezone.utc).isoformat()],
        "subject": ["job-" + os.environ["ID"]],
        "source": ["claude-dispatch"], "written_by": ["claude-dispatch"],
        "executor": ["claude"], "scope": ["tony"], "bank": ["devin-handoff"]}
if os.environ.get("Q"):
    meta["question"] = [os.environ["Q"]]
body = f"Job {os.environ['ID']} on {os.environ['HOSTN']} (claude): {os.environ['ST']}."
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

_meta_write() { # dir repo worktree branch unit default_branch
  python3 - "$1" "$2" "$3" "$4" "$5" "$6" <<'PY'
import json, os, sys
from datetime import datetime, timezone
d, repo, wt, branch, unit, dbranch = sys.argv[1:7]
meta = {"repo": repo, "worktree": wt, "branch": branch, "unit": unit,
        "default_branch": dbranch,
        "base": f"origin/{dbranch}" if dbranch else "",
        "executor": "claude", "agent": "claude-code",
        "model": os.environ.get("CLAUDE_MODEL_EFFECTIVE", ""),
        "permission_mode": "see prompt", "started_at": datetime.now(timezone.utc).isoformat()}
json.dump(meta, open(f"{d}/meta.json", "w"), indent=1)
PY
}

_claude_run() { # unit worktree prompt_file extra-args...
  local unit="$1" wt="$2" prompt="$3"; shift 3
  # Same wrap contract as devin-dispatch._devin_run: exit code lands in
  # $TASK_DIR/exit_code for the watch/close-out; --collect unloads the
  # unit when done.
  # DISPATCH_UNIT_PROPS: extra systemd-run properties (runner-agent's
  # task_run_props() splice — Nice/CPUWeight/RuntimeMaxSec etc).
  # shellcheck disable=SC2086
  systemd-run --user --unit="$unit" --working-directory="$wt" --collect \
    ${DISPATCH_UNIT_PROPS:-} \
    --setenv=HOME="$HOME" --setenv=PATH="$PATH" \
    --setenv=CLAUDE_BIN="$CLAUDE_BIN" \
    --setenv=CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}" \
    --setenv=CLAUDE_PERMISSION_MODE="$PERMISSION_MODE" \
    --setenv=CLAUDE_MODEL_EFFECTIVE="$MODEL" \
    --setenv=CLAUDE_EFFORT_EFFECTIVE="$EFFORT" \
    --setenv=PROMPT_FILE="$prompt" --setenv=TASK_DIR="$(dirname "$prompt")" \
    /bin/bash -c '
      # systemd expands dollar-vars in the unit command line BEFORE
      # bash sees it — every shell dollar must be written $$ or it
      # resolves against the unit env (empty for bash-locals).
      args=(-p --output-format stream-json --verbose)
      case "$$CLAUDE_PERMISSION_MODE" in
        bypassPermissions) args+=(--dangerously-skip-permissions) ;;
        *) args+=(--permission-mode "$$CLAUDE_PERMISSION_MODE"
                  --permission-prompts none) ;;
      esac
      [ -n "$$CLAUDE_MODEL_EFFECTIVE" ] && args+=(--model "$$CLAUDE_MODEL_EFFECTIVE")
      [ -n "$$CLAUDE_EFFORT_EFFECTIVE" ] && args+=(--effort "$$CLAUDE_EFFORT_EFFECTIVE")
      # claude has no --prompt-file; read the file inside the unit and
      # pass the text as the positional prompt arg (argv-safe, no env
      # size limits).
      PROMPT="$$(cat "$$PROMPT_FILE")"
      rc=0
      "$$CLAUDE_BIN" "$${args[@]}" "$$@" "$$PROMPT" 2>&1 \
        | tee -a "$$TASK_DIR/transcript.jsonl"
      rc=$${PIPESTATUS[0]}
      echo "$$rc" > "$$TASK_DIR/exit_code"; exit "$$rc"' _ "$@"
}

cmd_start() {
  local repo="${1:?repo required}"; shift
  local task="$*"
  [[ -n $task ]] || { echo "usage: claude-dispatch start <repo> \"<task>\"" >&2; exit 2; }
  local root="${REPOS[$repo]:-}"
  [[ -n $root && -d $root ]] || { echo "unknown repo '$repo' (allowed: ${!REPOS[*]})" >&2; exit 1; }
  local dbranch="${REPO_DEFAULT_BRANCH[$repo]:-}"
  if [[ -z $dbranch ]]; then
    dbranch="$(git -C "$root" symbolic-ref --quiet --short \
      refs/remotes/origin/HEAD 2>/dev/null || true)"; dbranch="${dbranch#origin/}"
  fi
  : "${dbranch:=master}"
  git -C "$root" fetch -q origin "$dbranch" >/dev/null 2>&1 \
    || echo "warn: fetch origin/$dbranch failed — using last-fetched ref" >&2
  local base="origin/$dbranch"
  git -C "$root" rev-parse --verify --quiet "$base" >/dev/null || {
    if git -C "$root" rev-parse --verify --quiet "$dbranch" >/dev/null; then
      echo "warn: no $base — basing on local $dbranch" >&2; base="$dbranch"
    else
      echo "no $base in $root — cannot cut worktree from default branch" >&2
      exit 1
    fi
  }
  local id="$(date +%Y%m%d-%H%M%S)-$(_slug "$task")"
  local wt="$HOME/CascadeProjects/dispatch-wt-$id"
  local dir="$DISPATCH_DIR/tasks/$id"
  mkdir -p "$dir"
  git -C "$root" worktree add "$wt" -b "dispatch/$id" "$base" >/dev/null 2>&1 || {
    echo "worktree failed for $root (base $base)" >&2; exit 1; }
  cat > "$dir/prompt.txt" <<EOF
You are running unattended via claude-dispatch (a headless, user-triggered
Claude Code session). Work only inside this worktree. Do not commit to the
default branch, do not push, and do not deploy unless the task explicitly
says so. Access outside this worktree may be rejected, and in this mode a
rejected tool call ends the session — keep everything inside the worktree.
When finished, write your final summary to ./dispatch-outcome-$id.md in
this worktree (what changed or was found, the result, how to verify), then
end with the same one-paragraph summary as your last message. The
per-session name is deliberate — a shared dispatch-outcome.md conflicts on
every merge.
If you are blocked and need a decision from the user, write your question to
\$TASK_DIR/needs-input.txt (first line: one-line question, then context) and
stop — the operator is notified and can resume you with an answer.
If you raised a question and kept working, the reply may arrive while you
run: answers are appended to \$TASK_DIR/answers.jsonl (one JSON object per
line: {at, card, from, kind, request_id, answer}). Check it before finishing.
Lines may also carry kind:"comment" (card comms — Tony's notes, Ada's
[opinion] takes); weigh them as review input — request_id/answer lines
stay the authoritative answer channel.
If the work produces a decision, runbook, or new infra, write it to
docs/ssot/jobs/<domain>/<date>-<slug>.yml or reports/ before ending —
leave a trail.

Task: $task
EOF
  export CLAUDE_MODEL_EFFECTIVE="$MODEL" \
         CLAUDE_EFFORT_EFFECTIVE="$EFFORT" \
         CLAUDE_PERMISSION_MODE="$PERMISSION_MODE"
  _claude_run "devin-task-$id" "$wt" "$dir/prompt.txt"
  _meta_write "$dir" "$repo" "$wt" "dispatch/$id" "devin-task-$id" "$dbranch"
  mddb_job "$id" "running" "$task" &
  echo "$id"
}

# session id for followup: last "result" event in the stream transcript
_session_id() { # task_dir
  python3 - "$1/transcript.jsonl" <<'PY' 2>/dev/null || true
import json, sys
sid = ""
try:
    for line in open(sys.argv[1], errors="replace"):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") == "result" and ev.get("session_id"):
            sid = ev["session_id"]
except OSError:
    pass
print(sid)
PY
}

cmd_status() {
  local only="${1:-}"
  local d id unit state result ts repo
  for d in "$DISPATCH_DIR"/tasks/*/; do
    [[ -d $d ]] || continue
    id=$(basename "$d")
    [[ -n $only && $id != "$only" ]] && continue
    # only claude-owned tasks: meta.executor == claude (or pre-executor
    # dirs we own via prompt marker) — devin tasks share this root
    local ex
    ex=$(_meta_get "$d/meta.json" executor 2>/dev/null || true)
    [[ $ex == "claude" ]] || continue
    unit="devin-task-$id"
    state=$(systemctl --user show "$unit" -p ActiveState --value 2>/dev/null || true)
    result=$(systemctl --user show "$unit" -p Result --value 2>/dev/null || true)
    repo=$(_meta_get "$d/meta.json" repo 2>/dev/null || true)
    ts=$(stat -c %y "$d/transcript.jsonl" 2>/dev/null | cut -d. -f1 || true)
    printf '%-42s %-8s %-10s repo=%-14s transcript=%s\n' \
      "$id" "${state:-gone}" "${result:--}" "${repo:-?}" "${ts:-never}"
  done
}

cmd_followup() {
  local id="${1:?id required}"; shift
  local msg="$*"
  [[ -n $msg ]] || { echo "usage: claude-dispatch followup <id> \"<msg>\"" >&2; exit 2; }
  local d="$DISPATCH_DIR/tasks/$id" wt n sid
  [[ -d $d ]] || { echo "no task $id" >&2; exit 1; }
  wt=$(_meta_get "$d/meta.json" worktree)
  sid=$(_session_id "$d")
  rm -f "$d/needs-input.txt"
  n=$(( $(find "$d" -name 'fu-*.txt' | wc -l) + 1 ))
  printf '%s\n' "$msg" > "$d/fu-$n.txt"
  export CLAUDE_MODEL_EFFECTIVE="$MODEL" \
         CLAUDE_EFFORT_EFFECTIVE="$EFFORT" \
         CLAUDE_PERMISSION_MODE="$PERMISSION_MODE"
  if [[ -n $sid ]]; then
    _claude_run "devin-task-$id-fu$n" "$wt" "$d/fu-$n.txt" -r "$sid"
  else
    _claude_run "devin-task-$id-fu$n" "$wt" "$d/fu-$n.txt" -c
  fi
  echo "followup $n sent to $id"
}

cmd_logs() { journalctl --user -u "devin-task-${1:?id required}*" --no-pager "${@:2}"; }
cmd_tail() { tail -n "${2:-40}" "$DISPATCH_DIR/tasks/${1:?id required}/transcript.jsonl"; }

case "${1:-}" in
  start)    shift; cmd_start "$@" ;;
  status)   shift; cmd_status "$@" ;;
  followup) shift; cmd_followup "$@" ;;
  logs)     shift; cmd_logs "$@" ;;
  tail)     shift; cmd_tail "$@" ;;
  *) sed -n '2,30p' "$0"; exit 2 ;;
esac
