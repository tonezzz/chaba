#!/usr/bin/env bash
# job-run — dispatch and track a generic background job (ssh command, local
# script, scenario run) with the same completion reporting as devin-dispatch:
# chaba-admin event + iPhone push + job/<id> doc in the devin-handoff MDDB
# collection. Unlike devin-dispatch the emit happens INSIDE the job's
# systemd unit, so no watch timer is required.
#
#   job-run.sh start <id> "<desc>" -- <cmd...>   launch detached, prints id
#   job-run.sh status [id]                       list jobs / show one
#   job-run.sh tail <id> [lines]                 tail output.log
#   job-run.sh emit <id>                         re-emit completion (manual)
#
# Needs-input protocol: the job signals "blocked, needs Tony" by writing
# $TASK_DIR/needs-input.txt (first line = one-line question, rest = context)
# OR by exiting 42 — the wrapper then greps the last NEEDS-INPUT: line out of
# output.log. Either way the job doc gets status=awaiting-user and the push
# carries the question. Answering goes through Ada (devin_answer) or this
# repo's reports/dispatch ledger.
#
# Env: JOBRUN_DIR (default ~/.local/share/job-run), MDDB_URL,
#      JOB_COLLECTION (default ada-ha-bank-devin-handoff), HA_URL,
#      EVENT_LOG (chaba-event-log.py path), EVENT_SSH (fallback host).
set -uo pipefail

JOBRUN_DIR="${JOBRUN_DIR:-$HOME/.local/share/job-run}"
MDDB="${MDDB_URL:-http://100.74.146.0:11023/v1}"
COLLECTION="${JOB_COLLECTION:-ada-ha-bank-devin-handoff}"
HA_URL="${HA_URL:-https://tony-dell.taila0626a.ts.net:8123}"
EVENT_LOG="${EVENT_LOG:-$HOME/.config/home-assistant/scripts/chaba-event-log.py}"
EVENT_SSH="${EVENT_SSH:-tony-dell-lan}"
SECRET_ENV="${JOB_SECRET_ENV:-$HOME/.config/secrets/home-assistant-token.env}"
SELF="$(readlink -f "$0")"

_id_ok() { [[ "$1" =~ ^[a-z0-9][a-z0-9-]{1,60}$ ]]; }

_meta_write() { # dir desc cmdline
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys, socket
from datetime import datetime, timezone
d, desc, cmd = sys.argv[1:4]
meta = {"desc": desc, "cmd": cmd, "host": socket.gethostname(),
        "started_at": datetime.now(timezone.utc).isoformat()}
json.dump(meta, open(f"{d}/meta.json", "w"), indent=1)
PY
}

_first_line() { head -1 "$1" 2>/dev/null | cut -c1-300; }

_needs_input() { # task_dir -> prints question, rc 0 if blocked
  local d="$1" q
  if [ -f "$d/needs-input.txt" ]; then
    _first_line "$d/needs-input.txt"; return 0
  fi
  q=$(grep -oE "NEEDS-INPUT:.*" "$d/output.log" 2>/dev/null | tail -1 | sed 's/^NEEDS-INPUT:[[:space:]]*//')
  if [ -n "$q" ]; then
    printf '%s\n' "$q" | cut -c1-300
    printf '%s\n' "$q" > "$d/needs-input.txt"
    return 0
  fi
  return 1
}

mddb_job() { # id status summary question — best-effort, rc always 0
  local id="$1" st="$2" summ="$3" q="${4:-}"
  ID="$id" ST="$st" SUMM="$summ" Q="$q" COLL="$COLLECTION" \
  HOSTN="$(hostname)" python3 - <<'PY' | curl -sf -m 15 -X POST \
      -H "Content-Type: application/json" -d @- "$MDDB/add" >/dev/null 2>&1
import json, os
from datetime import datetime, timezone
meta = {"kind": ["job"], "status": [os.environ["ST"]],
        "job_id": [os.environ["ID"]], "host": [os.environ["HOSTN"]],
        "ts": [datetime.now(timezone.utc).isoformat()],
        "subject": ["job-" + os.environ["ID"]],
        "source": ["job-run"], "written_by": ["job-run"],
        "scope": ["tony"], "bank": ["devin-handoff"]}
if os.environ.get("Q"):
    meta["question"] = [os.environ["Q"]]
body = f"Job {os.environ['ID']} on {os.environ['HOSTN']}: {os.environ['ST']}."
if os.environ.get("Q"):
    body += f"\n\nNeeds input: {os.environ['Q']}"
if os.environ.get("SUMM"):
    body += f"\n\n{os.environ['SUMM']}"
print(json.dumps({"collection": os.environ["COLL"],
                  "key": "job/" + os.environ["ID"], "lang": "en",
                  "contentMd": body, "meta": meta}))
PY
  return 0
}

notify_iphone() { # title message — best-effort
  set -a; . "$SECRET_ENV" 2>/dev/null; set +a
  local token="${HA_LONG_LIVED_TOKEN:-${HASS_TOKEN:-}}"
  [ -n "$token" ] || return 0
  TITLE="$1" MSG="$2" python3 - <<'PY' | curl -sf -m 10 -X POST \
      -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
      -d @- "$HA_URL/api/services/notify/mobile_app_tony_ip" >/dev/null 2>&1
import json, os
print(json.dumps({"title": os.environ["TITLE"],
                  "message": os.environ["MSG"][:500]}))
PY
  return 0
}

emit_event() { # title severity requires_response body — best-effort
  local payload
  payload=$(TITLE="$1" SEV="$2" RR="$3" BODY="$4" python3 - <<'PY'
import json, os
print(json.dumps({"title": os.environ["TITLE"], "category": "job-run",
    "source": "job-run", "severity": os.environ["SEV"],
    "requires_response": os.environ["RR"] == "true",
    "body": os.environ["BODY"]}))
PY
)
  if [ -x "$EVENT_LOG" ] || [ -f "$EVENT_LOG" ]; then
    printf '%s\n' "$payload" | python3 "$EVENT_LOG" add - >/dev/null 2>&1 && return 0
  fi
  printf '%s\n' "$payload" | ssh -o BatchMode=yes -o ConnectTimeout=8 "$EVENT_SSH" \
      "python3 ~/.config/home-assistant/scripts/chaba-event-log.py add -" \
      >/dev/null 2>&1 || true
  return 0
}

emit_done() { # task_dir — runs INSIDE the unit after the command exits
  local d="$1" id="$2" ec summ q st
  ec=$(cat "$d/exit_code" 2>/dev/null || echo "?")
  summ=$(tail -20 "$d/output.log" 2>/dev/null | cut -c1-2000)
  if q=$(_needs_input "$d"); then
    st="awaiting-user"
    emit_event "job $id: needs input" warn true \
        "$(printf 'Job %s is blocked.\n\nQuestion: %s\n\n%s' "$id" "$q" "$summ")"
    notify_iphone "Job needs input" "${id}: ${q} — reply via Ada or Devin"
    mddb_job "$id" "$st" "$summ" "$q"
  elif [ "$ec" = "0" ]; then
    st="done"
    emit_event "job $id: done" info false "$summ"
    notify_iphone "Job done" "${id}: $(printf '%s' "$summ" | head -3 | tr '\n' ' ' | cut -c1-200)"
    mddb_job "$id" "$st" "$summ"
  else
    st="failed"
    emit_event "job $id: FAILED (exit $ec)" fail true "$summ"
    notify_iphone "Job FAILED" "${id} exit $ec: $(printf '%s' "$summ" | tail -3 | tr '\n' ' ' | cut -c1-180)"
    mddb_job "$id" "$st" "$summ"
  fi
  python3 - "$d" "$st" <<'PY' 2>/dev/null || true
import json, sys
from datetime import datetime, timezone
d, st = sys.argv[1:3]
m = json.load(open(f"{d}/meta.json"))
m["status"] = st
m["finished_at"] = datetime.now(timezone.utc).isoformat()
json.dump(m, open(f"{d}/meta.json", "w"), indent=1)
PY
  return 0
}

cmd_start() {
  local id="${1:?id required}" desc="${2:?desc required}"
  shift 2
  [[ "$1" == "--" ]] && shift
  [ $# -gt 0 ] || { echo "usage: job-run start <id> <desc> -- <cmd...>" >&2; exit 2; }
  _id_ok "$id" || { echo "bad id '$id' (a-z0-9-)" >&2; exit 2; }
  local d="$JOBRUN_DIR/tasks/$id"
  mkdir -p "$d"
  printf '%s\n' "$*" > "$d/cmd.txt"
  _meta_write "$d" "$desc" "$*"
  mddb_job "$id" "running" "$desc" &
  systemd-run --user --unit="job-run-$id" --collect \
    --setenv=HOME="$HOME" --setenv=PATH="$PATH" \
    --setenv=TASK_DIR="$d" --setenv=JOB_ID="$id" \
    --setenv=JOBRUN_SELF="$SELF" --setenv=MDDB_URL="$MDDB" \
    --setenv=JOB_COLLECTION="$COLLECTION" --setenv=HA_URL="$HA_URL" \
    --setenv=EVENT_LOG="$EVENT_LOG" --setenv=EVENT_SSH="$EVENT_SSH" \
    --setenv=JOB_SECRET_ENV="$SECRET_ENV" \
    --setenv=DISPATCH_PERMISSION_MODE="${DISPATCH_PERMISSION_MODE:-}" \
    --setenv=DISPATCH_UNIT_PROPS="${DISPATCH_UNIT_PROPS:-}" \
    /bin/bash -c 'rc=0; "$@" >> "$TASK_DIR/output.log" 2>&1 || rc=$?; \
      echo "$rc" > "$TASK_DIR/exit_code"; \
      source "$JOBRUN_SELF"; emit_done "$TASK_DIR" "$JOB_ID"; \
      exit "$rc"' _ "$@"
  echo "$id"
}

cmd_status() {
  local only="${1:-}" d id st ec ts
  for d in "$JOBRUN_DIR"/tasks/*/; do
    [[ -d $d ]] || continue
    id=$(basename "$d")
    [[ -n $only && $id != "$only" ]] && continue
    st=$(systemctl --user show "job-run-$id" -p ActiveState --value 2>/dev/null || true)
    ec=$(cat "$d/exit_code" 2>/dev/null || echo "-")
    ts=$(stat -c %y "$d/output.log" 2>/dev/null | cut -d. -f1 || echo never)
    printf '%-34s %-10s exit=%-4s out=%s\n' "$id" "${st:-gone}" "$ec" "$ts"
  done
}

cmd_tail() { tail -n "${2:-40}" "$JOBRUN_DIR/tasks/${1:?id required}/output.log"; }

cmd_emit() { local d="$JOBRUN_DIR/tasks/${1:?id required}"; emit_done "$d" "$1"; }

# Only dispatch when executed — the unit wrapper sources this file for
# emit_done/_needs_input and must not hit the usage/exit branch.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-}" in
    start)  shift; cmd_start "$@" ;;
    status) shift; cmd_status "$@" ;;
    tail)   shift; cmd_tail "$@" ;;
    emit)   shift; cmd_emit "$@" ;;
    *) sed -n '2,22p' "$0"; exit 2 ;;
  esac
fi
