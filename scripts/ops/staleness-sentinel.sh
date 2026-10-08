#!/usr/bin/env bash
# staleness-sentinel.sh — flag services running older code than what's on disk.
#
# Motivation (2026-10-07): board-api served pre-commit code for ~10h after the
# card-level `ask:` fix landed — commits/deploys updated files but nobody
# restarted the unit. This sentinel makes that bug class visible: for each
# running service it compares the process start time (ActiveEnterTimestamp)
# against the mtime of every file referenced by ExecStart (script paths,
# binaries, config drop-ins). Newer file than process = stale.
#
# Also flags units whose definition changed on disk but was never loaded
# (NeedDaemonReload=yes) — the "edited the .service, forgot daemon-reload"
# sibling of the same bug.
#
# Scope: user units always; system units when run with --system or by root.
# Containers are skipped — ExecStart=podman run ... serves a volume mount;
# staleness there needs image-tag comparison, a different check entirely.
#
# JSONL log:   ~/var/chaba/health/staleness-sentinel.log (rotated 10000 lines)
# State:       ~/var/chaba/health/staleness-state/<unit>.stale  (one alert per episode)
# Alerts:      chaba recent-event + HA event log (same path as ssh-canary)
#
# Env overrides:
#   STALENESS_SKIP   space-separated unit-name globs to skip
#                    (default: oneshot-ish + container/template noise)
#   EVENT_SSH        host:port for the HA chaba-event-log post (default dell LAN)
# Exit 0 always — findings go to the log + events, not the exit code.
set -uo pipefail

LOG_DIR="$HOME/var/chaba/health"
LOG_FILE="$LOG_DIR/staleness-sentinel.log"
STATE_DIR="$LOG_DIR/staleness-state"
mkdir -p "$LOG_DIR" "$STATE_DIR"

EVENT_SSH="${EVENT_SSH:-192.168.2.67}"
SKIP="${STALENESS_SKIP:-cast-desktop@*.service dbus-*.service devin-task-*.service}"
WITH_SYSTEM=0
[ "${1:-}" = "--system" ] && WITH_SYSTEM=1
[ "$(id -u)" = 0 ] && WITH_SYSTEM=1

emit_event() {  # $1 severity  $2 body   (same shape as ssh-canary)
    local sev=$1 body=$2 repo="" payload
    for d in "$HOME/CascadeProjects/chaba" "$HOME/CascadeProjects/chaba-tony-dell"; do
        [ -f "$d/scripts/chaba/recent-event.py" ] && repo="$d" && break
    done
    if [ -n "$repo" ]; then
        python3 "$repo/scripts/chaba/recent-event.py" --text "staleness: $body" \
            --ref staleness-sentinel --ttl-hours 24 >/dev/null 2>&1 || true
    fi
    payload=$(SEV="$sev" BODY="$body" python3 - <<'PY'
import json, os
print(json.dumps({"title": "staleness sentinel", "category": "ops-canary",
    "source": "staleness-sentinel", "severity": os.environ["SEV"],
    "requires_response": os.environ["SEV"] != "info",
    "body": os.environ["BODY"]}))
PY
)
    printf '%s\n' "$payload" | ssh -o BatchMode=yes -o ConnectTimeout=5 "$EVENT_SSH" \
        "python3 ~/.config/home-assistant/scripts/chaba-event-log.py add -" \
        >/dev/null 2>&1 || true
}

log() {  # $1 json fields
    local line
    line=$(printf '{"ts":"%s","host":"%s",%s}' "$(date -Is)" "$(hostname)" "$1")
    echo "$line" >>"$LOG_FILE"
    [ "$(wc -l <"$LOG_FILE")" -gt 10000 ] && tail -5000 "$LOG_FILE" >"$LOG_FILE.tmp" \
        && mv "$LOG_FILE.tmp" "$LOG_FILE"
}

skip_unit() {  # $1 unit name
    local u=$1 g
    for g in $SKIP; do case "$u" in $g) return 0;; esac; done
    return 1
}

scan_scope() {  # $1 = --user | "" (system)
    local scope_flag=$1 unit props start_us frag_ts changed=0
    while IFS= read -r unit; do
        skip_unit "$unit" && continue
        props=$(systemctl $scope_flag show "$unit" \
            -p ExecStart -p MainPID -p NeedDaemonReload \
            -p SubState -p Type 2>/dev/null) || continue
        # only long-running services — oneshot exits legitimately
        grep -q "^SubState=running" <<<"$props" || continue
        grep -q "^Type=oneshot" <<<"$props" && continue

        # process start = /proc/<pid> inode mtime (portable across systemd
        # versions — ActiveEnterTimestampUSec isn't on 259)
        local mpid=$(sed -n 's/^MainPID=//p' <<<"$props")
        [ -n "$mpid" ] && [ "$mpid" != "0" ] && [ -d "/proc/$mpid" ] || continue
        local pm
        pm=$(stat -c %Y "/proc/$mpid" 2>/dev/null) || continue

        if grep -q "^NeedDaemonReload=yes" <<<"$props"; then
            echo "RELOAD:$unit"
            continue
        fi

        # every existing file path in the ExecStart argv that is newer than
        # the process start makes the unit stale. argv looks like:
        #   ExecStart={ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /srv/x.py ; ... }
        while IFS= read -r arg; do
            [ -f "$arg" ] || continue
            case "$arg" in
                # outputs the unit writes itself — always newer, never stale
                *.log|*/.cache/*|*.m3u8|*.ts|*.pid|*.lock|*/.local/state/*) continue ;;
                *.py|*.sh|*.mjs|*.js|*.rb|*.pl|*/bin/*|/home/*|/srv/*|/opt/*|/etc/*|/usr/local/*) ;;
                *) continue ;;
            esac
            local fm=$(stat -c %Y "$arg" 2>/dev/null) || continue
            if [ "$fm" -gt "$pm" ]; then
                echo "STALE:$unit:$arg:$((fm - pm))s-newer"
            fi
        done < <(tr ';' '\n' <<<"$(sed -n 's/^ExecStart=//p' <<<"$props")" | tr ' ' '\n' | grep '^/')
    done < <(systemctl $scope_flag list-units --type=service --state=running \
             --no-legend --no-pager --plain 2>/dev/null | awk '{print $1}')
}

findings=$(scan_scope --user; [ $WITH_SYSTEM = 1 ] && scan_scope "")
stale=(); reload=()
while IFS= read -r f; do
    case "$f" in
        STALE:*)  unit=${f#STALE:}; unit=${unit%%:*}; stale+=("${f#STALE:}") ;;
        RELOAD:*) reload+=("${f#RELOAD:}") ;;
    esac
done <<<"${findings:-}"

# dedupe unit names (a unit may have several stale files)
mapfile -t stale_units < <(printf '%s\n' "${stale[@]:-}" | cut -d: -f1 | sort -u)
mapfile -t stale < <(printf '%s\n' "${stale[@]:-}" | sort -u)

now_stale=$(printf '%s\n' "${stale_units[@]:-}" "${reload[@]:-}" | grep -v '^$' | sort -u)

# alert once per episode per unit; clear state when fresh again
for u in $now_stale; do
    state="$STATE_DIR/$u.stale"
    detail=$(printf '%s\n' "${stale[@]:-}" | grep "^$u:" | head -3 | tr '\n' ' ')
    case " ${reload[*]:-} " in *" $u "*) detail="unit file changed, daemon-reload needed";; esac
    log "\"unit\":\"$u\",\"state\":\"stale\",\"detail\":\"$detail\""
    if [ ! -f "$state" ]; then
        touch "$state"
        emit_event warn "$u is running stale code ($detail)"
    fi
done
for f in "$STATE_DIR"/*.stale; do
    [ -e "$f" ] || break
    u=$(basename "$f" .stale)
    if ! printf '%s\n' "$now_stale" | grep -qxF "$u"; then
        rm -f "$f"
        log "\"unit\":\"$u\",\"state\":\"recovered\""
        emit_event info "$u is fresh again (restarted or reloaded)"
    fi
done

# compact status file — consumers (Node-RED flows, dashboards) read this
# instead of parsing the JSONL log
python3 - "$LOG_DIR/staleness-latest.json" "$now_stale" <<'PY'
import json, sys
stale = sys.argv[2].split()
stale = [u for u in stale if u]
out = {"ts": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
       "host": __import__("socket").gethostname(),
       "stale_units": stale, "stale_count": len(stale)}
with open(sys.argv[1], "w") as f:
    json.dump(out, f)
PY
exit 0
