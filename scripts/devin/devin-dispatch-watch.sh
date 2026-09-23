#!/usr/bin/env bash
# devin-dispatch-watch — detect finished devin-dispatch tasks, report outcome.
#
# Runs from devin-dispatch-watch.timer (every 5 min) on tony-dell. For each
# task in ~/.local/share/devin-dispatch/tasks/<id>/ whose devin-task-<id>*
# units are all inactive, it:
#   1. Reads the outcome from transcript.json — the LAST step with
#      source=agent (devin -p sessions do NOT write history_*.md, so the
#      bank sync never sees them; this is the only outcome path).
#   2. Emits a chaba-admin Events entry via chaba-event-log.py (local).
#   3. Sends an iPhone notification via notify.mobile_app_tony_ip on
#      tony-ha (loopback REST; token from ~/.config/secrets/home-assistant-token.env).
#   4. Writes the outcome doc into MDDB ada-ha-bank-devin-tony as
#      devin/<session_id> (written_by=devin-dispatch — remote-only doc,
#      the vault sync leaves these alone).
#   5. Stamps meta.json: result, finished_at, notified_at — never re-fires.
#
# Install: systemd/devin-dispatch-watch.{service,timer} -> user units.
set -uo pipefail

DISPATCH_DIR="${DISPATCH_DIR:-$HOME/.local/share/devin-dispatch}"
EVENT_LOG="$HOME/.config/home-assistant/scripts/chaba-event-log.py"
MDDB="${MDDB_URL:-http://100.74.146.0:11023/v1}"
COLLECTION="ada-ha-bank-devin-tony"
HA_URL="http://127.0.0.1:8123"

log() { echo "$(date -Iseconds) $*"; }

# Latest unit for a task = the followup unit with the highest N, else the
# main unit. Prints "<unit> <ActiveState> <Result>"; empty if none loaded.
latest_unit() {
    local id="$1" best="" n
    for u in $(systemctl --user list-units --all --no-legend \
               "devin-task-$id*" 2>/dev/null | awk '{print $1}' | sed 's/\.service$//'); do
        case "$u" in
            *-fu[0-9]*) n="${u##*-fu}" ;;
            *) n=0 ;;
        esac
        [ "$n" -ge "${bestn:--1}" ] && { best="$u"; bestn="$n"; }
    done
    [ -n "$best" ] || return 0
    local st res
    st=$(systemctl --user show "$best" -p ActiveState --value 2>/dev/null)
    res=$(systemctl --user show "$best" -p Result --value 2>/dev/null)
    echo "$best $st $res"
}

any_active() {
    systemctl --user list-units --state=active,activating --no-legend \
        "devin-task-$1*" 2>/dev/null | grep -q .
}

outcome() { # transcript.json -> last agent message (truncated)
    python3 - "$1" <<'PY'
import json, sys
try:
    t = json.load(open(sys.argv[1]))
    msgs = [s.get("message", "") for s in t.get("steps", [])
            if s.get("source") == "agent" and s.get("message")]
    print((msgs[-1] if msgs else "(no agent output)")[:3000])
except Exception as exc:
    print(f"(transcript unreadable: {exc})")
PY
}

session_id() {
    python3 - "$1" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("session_id") or "")
except Exception:
    pass
PY
}

meta_stamp() { # dir result — adds finished/notified fields
    python3 - "$1" "$2" <<'PY'
import json, sys
from datetime import datetime, timezone
d, result = sys.argv[1:3]
m = json.load(open(f"{d}/meta.json"))
m["result"] = result
m["finished_at"] = datetime.now(timezone.utc).isoformat()
m["notified_at"] = m["finished_at"]
json.dump(m, open(f"{d}/meta.json", "w"), indent=1)
PY
}

already_done() {
    python3 - "$1" <<'PY'
import json, sys
try:
    sys.exit(0 if json.load(open(sys.argv[1] + "/meta.json")).get("notified_at") else 1)
except Exception:
    sys.exit(1)
PY
}

emit_event() { # title severity requires_response body
    TITLE="$1" SEV="$2" RR="$3" BODY="$4" python3 - <<'PY' | python3 "$EVENT_LOG_LOCAL" add - >/dev/null 2>&1 || true
import json, os
print(json.dumps({"title": os.environ["TITLE"], "category": "devin-dispatch",
    "source": "devin-dispatch-watch",
    "severity": os.environ["SEV"],
    "requires_response": os.environ["RR"] == "true",
    "body": os.environ["BODY"]}))
PY
}

notify_iphone() { # title message
    set -a; . "$HOME/.config/secrets/home-assistant-token.env" 2>/dev/null
    set +a
    local token="${HA_LONG_LIVED_TOKEN:-$HASS_TOKEN}"
    [ -n "$token" ] || return 0
    TITLE="$1" MSG="$2" python3 - <<'PY' | curl -sf -X POST \
        -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
        -d @- "$HA_URL_LOCAL/api/services/notify/mobile_app_tony_ip" >/dev/null 2>&1 || true
import json, os
print(json.dumps({"title": os.environ["TITLE"],
                  "message": os.environ["MSG"][:500]}))
PY
}

mddb_add() { # key body
    KEY="$1" BODY="$2" python3 - <<'PY' | curl -sf -X POST \
        -H "Content-Type: application/json" -d @- "$MDDB/add" >/dev/null 2>&1 || true
import json, os
body = os.environ["BODY"]
print(json.dumps({
    "collection": "ada-ha-bank-devin-tony",
    "key": os.environ["KEY"], "lang": "en", "contentMd": body,
    "meta": {"kind": ["note"], "status": ["active"], "scope": ["tony"],
             "bank": ["devin"], "source": ["import"],
             "written_by": ["devin-dispatch"], "subject": ["devin-dispatch"],
             "attribute": [os.environ["KEY"].split("/")[-1]]}}))
PY
}

EVENT_LOG_LOCAL="$EVENT_LOG"
HA_URL_LOCAL="$HA_URL"

shopt -s nullglob
for d in "$DISPATCH_DIR"/tasks/*/; do
    id=$(basename "$d")
    [ -f "$d/meta.json" ] || continue
    already_done "$d" && continue
    any_active "$id" && continue

    read -r unit state result <<<"$(latest_unit "$id")"
    if [ -z "${unit:-}" ]; then
        # dispatch uses systemd-run --collect: finished units are unloaded
        # entirely. No unit + transcript = ran to completion and was GC'd.
        [ -f "$d/transcript.json" ] || continue   # never started / still pending
        unit="(collected)"; result="success"
    fi
    out=$(outcome "$d/transcript.json")
    sid=$(session_id "$d/transcript.json")

    if [ "$result" = "success" ]; then
        sev="info"; rr="false"; label="done"
    else
        sev="fail"; rr="true"; label="FAILED ($result)"
    fi

    log "task $id finished: unit=$unit result=${result:-none} sid=${sid:-?}"
    emit_event "devin task $id: $label" "$sev" "$rr" "$out"
    notify_iphone "Devin task ${label}" "${id}: ${out:0:200}"
    [ -n "$sid" ] && mddb_add "devin/$sid" \
        "$(printf 'Dispatched task %s (unit %s, result %s).\n\n%s' "$id" "$unit" "$result" "$out")"
    meta_stamp "$d" "${result:-unknown}"
done

# P4: keep focus-inbox entries in sync with the ada-ha-bank-devin-handoff
# bank so repo triage picks up pending Ada-written specs. Best-effort —
# never block or fail the watch on it.
HANDOFF_RENDERER="$HOME/CascadeProjects/chaba/scripts/devin/render-handoff-inbox.py"
[ -f "$HANDOFF_RENDERER" ] && log "handoff-inbox: $(python3 "$HANDOFF_RENDERER" 2>&1)" || true
