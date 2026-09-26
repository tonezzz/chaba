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

meta_stamp() { # dir result fu_index channels_done — stamps per-channel
    # flags + notified_fu so follow-up completions re-fire and failed
    # channels retry on the next run instead of going silent.
    python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, sys
from datetime import datetime, timezone
d, result, fu, chans = sys.argv[1:5]
m = json.load(open(f"{d}/meta.json"))
now = datetime.now(timezone.utc).isoformat()
m["result"] = result
m["finished_at"] = now
m["notified_fu"] = int(fu)
m["notified_at"] = now
for c in chans.split(","):
    if c:
        m[f"{c}_at"] = now
json.dump(m, open(f"{d}/meta.json", "w"), indent=1)
PY
}

already_done() { # dir fu_index — done if notified_fu covers latest unit
    python3 - "$1" "$2" <<'PY'
import json, sys
try:
    m = json.load(open(sys.argv[1] + "/meta.json"))
    fu = int(sys.argv[2])
    if m.get("notified_fu") is not None:
        sys.exit(0 if int(m["notified_fu"]) >= fu else 1)
    # legacy tasks: notified_at covers only the base unit (fu index 0)
    sys.exit(0 if (fu == 0 and m.get("notified_at")) else 1)
except Exception:
    sys.exit(1)
PY
}

latest_fu() { # highest follow-up index present (0 = base unit only)
    local d="$1" n=0 f
    for f in "$d"/fu-*.txt; do
        [ -f "$f" ] || continue
        local k="${f##*/fu-}"; k="${k%.txt}"
        [ "$k" -gt "$n" ] 2>/dev/null && n="$k"
    done
    echo "$n"
}

journal_result() { # infer exit result from journal even after --collect GC
    # Prints "success"|"failed"|"" — the unit's Result field is gone once
    # collected, but journal lines like 'devin-task-X.service: Succeeded.'
    # and 'Failed with result ...' persist.
    journalctl --user-unit "devin-task-$1.service" --no-pager -o cat \
        2>/dev/null | grep -oE "Succeeded\.|Failed with result '[a-z-]+'" \
        | tail -1 | sed "s/Succeeded\./success/;s/Failed with result '\([a-z-]*\)'/\1/"
}

emit_event() { # title severity requires_response body — rc 0 on success
    TITLE="$1" SEV="$2" RR="$3" BODY="$4" python3 - <<'PY' | python3 "$EVENT_LOG_LOCAL" add - >/dev/null 2>&1
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
        -d @- "$HA_URL_LOCAL/api/services/notify/mobile_app_tony_ip" >/dev/null 2>&1
import json, os
print(json.dumps({"title": os.environ["TITLE"],
                  "message": os.environ["MSG"][:500]}))
PY
}

mddb_add() { # key body
    KEY="$1" BODY="$2" python3 - <<'PY' | curl -sf -X POST \
        -H "Content-Type: application/json" -d @- "$MDDB/add" >/dev/null 2>&1
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

mddb_job() { # id status summary question — job/<id> doc in devin-handoff,
    # the ledger Ada's devin_pending and the Report dispatch layer read.
    local id="$1" st="$2" summ="${3:-}" q="${4:-}"
    ID="$id" ST="$st" SUMM="$summ" Q="$q" python3 - <<'PY' | curl -sf -m 15 \
        -X POST -H "Content-Type: application/json" -d @- \
        "$MDDB/add" >/dev/null 2>&1
import json, os, socket
from datetime import datetime, timezone
meta = {"kind": ["job"], "status": [os.environ["ST"]],
        "job_id": [os.environ["ID"]], "host": [socket.gethostname()],
        "ts": [datetime.now(timezone.utc).isoformat()],
        "subject": ["job-" + os.environ["ID"]],
        "source": ["devin-dispatch"], "written_by": ["devin-dispatch"],
        "scope": ["tony"], "bank": ["devin-handoff"]}
if os.environ.get("Q"):
    meta["question"] = [os.environ["Q"]]
body = f"Job {os.environ['ID']} on {socket.gethostname()}: {os.environ['ST']}."
if os.environ.get("Q"):
    body += f"\n\nNeeds input: {os.environ['Q']}"
if os.environ.get("SUMM"):
    body += f"\n\n{os.environ['SUMM'][:2000]}"
print(json.dumps({"collection": "ada-ha-bank-devin-handoff",
                  "key": "job/" + os.environ["ID"], "lang": "en",
                  "contentMd": body, "meta": meta}))
PY
    return 0
}

EVENT_LOG_LOCAL="$EVENT_LOG"
HA_URL_LOCAL="$HA_URL"

shopt -s nullglob
for d in "$DISPATCH_DIR"/tasks/*/; do
    id=$(basename "$d")
    [ -f "$d/meta.json" ] || continue
    fu=$(latest_fu "$d")
    already_done "$d" "$fu" && continue
    any_active "$id" && continue

    read -r unit state result <<<"$(latest_unit "$id")"
    if [ -z "${unit:-}" ]; then
        # dispatch uses systemd-run --collect: finished units are unloaded
        # entirely. No unit + transcript = ran and was GC'd — but the unit's
        # Result is gone too, so prefer the exit_code the dispatch wrapper
        # records, then the journal; only fall back to inference last.
        [ -f "$d/transcript.json" ] || continue   # never started / still pending
        if [ -f "$d/exit_code" ]; then
            ec=$(cat "$d/exit_code" 2>/dev/null)
            unit="(collected,exit=$ec)"
            [ "$ec" = "0" ] && result="success" || result="exit-$ec"
        else
            unit="(collected)"
            result=$(journal_result "$id")
            # No record at all (tasks from before exit_code): a transcript
            # with agent output is the best available signal of completion.
            [ -z "$result" ] && { result="success"; unit="(collected,inferred)"; }
        fi
    fi
    out=$(outcome "$d/transcript.json")
    sid=$(session_id "$d/transcript.json")

    # needs-input.txt: the dispatched session wrote a question instead of
    # finishing — route it to Tony with the question text and flip the
    # job/<id> doc to awaiting-user so Ada's devin_pending can pick it up.
    question=""
    if [ -f "$d/needs-input.txt" ]; then
        question=$(head -1 "$d/needs-input.txt" | cut -c1-300)
    fi

    if [ -n "$question" ]; then
        sev="warn"; rr="true"; label="needs input"
    elif [ "$result" = "success" ]; then
        sev="info"; rr="false"; label="done"
    else
        sev="fail"; rr="true"; label="FAILED ($result)"
    fi

    log "task $id finished: unit=$unit fu=$fu result=${result:-none} sid=${sid:-?}${question:+ q=$question}"
    chans=""
    evbody="$out"
    [ -n "$question" ] && evbody="Question: ${question}"$'\n\n'"$out"
    emit_event "devin task $id: $label" "$sev" "$rr" "$evbody" && chans="event"
    if [ -n "$question" ]; then
        notify_iphone "Devin job needs input" \
            "${id}: ${question} — reply via Ada or Devin" && chans="$chans,notify"
    else
        notify_iphone "Devin task ${label}" \
            "${id}: ${out:0:200}" && chans="$chans,notify"
    fi
    if [ -n "$question" ]; then jstate="awaiting-user"
    elif [ "$result" = "success" ]; then jstate="done"; else jstate="failed"; fi
    mddb_job "$id" "$jstate" "$out" "$question" && chans="$chans,jobdoc"
    if [ -n "$sid" ]; then
        mddb_add "devin/$sid" \
            "$(printf 'Dispatched task %s (unit %s, result %s).\n\n%s' "$id" "$unit" "$result" "$out")" \
            && chans="$chans,mddb"
    fi
    [ -n "$chans" ] || log "WARN: all channels failed for $id — will retry next run"
    meta_stamp "$d" "${result:-unknown}" "$fu" "$chans"
done

# P4: keep focus-inbox entries in sync with the ada-ha-bank-devin-handoff
# bank so repo triage picks up pending Ada-written specs. Best-effort —
# never block or fail the watch on it.
HANDOFF_RENDERER="$HOME/CascadeProjects/chaba/scripts/devin/render-handoff-inbox.py"
[ -f "$HANDOFF_RENDERER" ] && log "handoff-inbox: $(python3 "$HANDOFF_RENDERER" 2>&1)" || true
