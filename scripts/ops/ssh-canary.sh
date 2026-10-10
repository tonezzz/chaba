#!/usr/bin/env bash
# ssh-canary.sh — probe SSH reachability of a host over LAN and tailnet.
#
# Runs on tony-omen as a user timer (ssh-canary.timer, ~1 min cadence).
# Motivation: tony-dell periodically stalls hard enough that TCP connects
# succeed but the SSH banner/handshake never completes — classic sign of
# host-wide I/O or memory pressure wedging sshd before auth.
#
# Per target it measures, in milliseconds:
#   tcp_ms    — TCP connect to <host>:22
#   banner_ms — time until the "SSH-…" banner line arrives (sshd scheduler pressure)
#   ssh_ms    — full BatchMode ssh roundtrip (auth + spawn; needs key auth)
#
# JSONL log:   ~/var/chaba/health/ssh-canary.log (rotated at 10000 lines)
# State:       ~/var/chaba/health/ssh-canary-state/<name>.fails
# Incidents:   on recovery after an alert, remote pressure + journal evidence
#              is pulled to ~/var/chaba/health/ssh-canary-incident-<ts>-<name>.log
#
# Alerts: after ALERT_AFTER consecutive failed probes, writes a local
# chaba recent-event (shows up in the Report feed) and best-effort posts
# to the HA event log on EVENT_SSH. One event per episode.
#
# Env overrides:
#   SSH_CANARY_TARGETS   space-separated "name|ssh-target|banner-host[:port]"
#   SSH_CANARY_CONNECT_TIMEOUT  (default 6)
#   SSH_CANARY_BANNER_TIMEOUT   (default 6)
#   SSH_CANARY_ALERT_AFTER      consecutive failures before alert (default 2)
#   EVENT_SSH                   ssh target for the HA chaba-event-log post
#                               (default: tony-dell over tailnet — survives LAN
#                               partitioning; LAN-only targets can't report a
#                               LAN-path outage)
# Exit 0 if every target answered the full ssh probe, 1 otherwise.
set -uo pipefail

LOG_DIR="$HOME/var/chaba/health"
LOG_FILE="$LOG_DIR/ssh-canary.log"
STATE_DIR="$LOG_DIR/ssh-canary-state"
mkdir -p "$LOG_DIR" "$STATE_DIR"

CONNECT_TIMEOUT="${SSH_CANARY_CONNECT_TIMEOUT:-6}"
BANNER_TIMEOUT="${SSH_CANARY_BANNER_TIMEOUT:-6}"
ALERT_AFTER="${SSH_CANARY_ALERT_AFTER:-2}"
EVENT_SSH="${EVENT_SSH:-tony-dell}"
PORT=22

TARGETS="${SSH_CANARY_TARGETS:-tony-dell-ts|tony-dell|100.68.142.13 tony-dell-lan|tony-dell-lan|192.168.2.67}"

ms() { echo "$1" | awk '{printf "%.1f", $1 * 1000}'; }  # seconds -> ms string

tcp_probe() {  # $1 host  -> echo ms or empty
    local host=$1 start end
    start=$EPOCHREALTIME
    if timeout "$CONNECT_TIMEOUT" bash -c "exec 3<>/dev/tcp/$host/$PORT" 2>/dev/null; then
        end=$EPOCHREALTIME
        ms "$(awk -v a="$start" -v b="$end" 'BEGIN{print b-a}')"
    fi
}

banner_probe() {  # $1 host -> "ms banner" or empty
    local host=$1 start end out
    start=$EPOCHREALTIME
    out=$(timeout "$BANNER_TIMEOUT" bash -c \
        "exec 3<>/dev/tcp/$host/$PORT && head -n 1 <&3" 2>/dev/null)
    case "$out" in
        SSH-*) end=$EPOCHREALTIME
               echo "$(ms "$(awk -v a="$start" -v b="$end" 'BEGIN{print b-a}')") $out" ;;
    esac
}

ssh_probe() {  # $1 ssh-target -> echo ms or empty
    local t=$1 start end
    start=$EPOCHREALTIME
    if ssh -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" \
           -o StrictHostKeyChecking=accept-new "$t" true 2>/dev/null; then
        end=$EPOCHREALTIME
        ms "$(awk -v a="$start" -v b="$end" 'BEGIN{print b-a}')"
    fi
}

emit_event() {  # $1 severity  $2 body
    local sev=$1 body=$2 repo="" payload
    for d in "$HOME/CascadeProjects/chaba" "$HOME/CascadeProjects/chaba-tony-dell"; do
        [ -f "$d/scripts/chaba/recent-event.py" ] && repo="$d" && break
    done
    if [ -n "$repo" ]; then
        python3 "$repo/scripts/chaba/recent-event.py" --text "ssh-canary: $body" \
            --ref ssh-canary --ttl-hours 24 >/dev/null 2>&1 || true
    fi
    payload=$(SEV="$sev" BODY="$body" python3 - <<'PY'
import json, os
print(json.dumps({"title": "ssh canary", "category": "ops-canary",
    "source": "ssh-canary", "severity": os.environ["SEV"],
    "requires_response": os.environ["SEV"] != "info",
    "body": os.environ["BODY"]}))
PY
)
    printf '%s\n' "$payload" | ssh -o BatchMode=yes -o ConnectTimeout=5 "$EVENT_SSH" \
        "python3 ~/.config/home-assistant/scripts/chaba-event-log.py add -" \
        >/dev/null 2>&1 || true
}

pull_incident() {  # $1 name  $2 ssh-target
    local name=$1 t=$2 f="$LOG_DIR/ssh-canary-incident-$(date +%Y%m%d-%H%M%S)-$name.log"
    ssh -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" "$t" '
        date; uptime
        echo "== pressure =="; cat /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory 2>/dev/null
        echo "== mem =="; free -h
        echo "== journal: ssh/tailscaled/smartd last 15min =="
        journalctl -u ssh.service -u tailscaled -u smartd --since "-15 min" --no-pager 2>/dev/null | tail -60
    ' >"$f" 2>&1 && echo "incident evidence: $f" || rm -f "$f"
}

any_fail=0
for spec in $TARGETS; do
    name=${spec%%|*}; rest=${spec#*|}
    t=${rest%%|*}; bhost=${rest#*|}
    bhost="${bhost:-$t}"

    tcp=$(tcp_probe "$bhost")
    read -r banner_ms banner <<<"$(banner_probe "$bhost")"
    ssh_ms=$(ssh_probe "$t")

    ok=1; err=""
    [ -z "$tcp" ]      && { ok=0; err="tcp-connect failed"; }
    [ -z "$banner_ms" ] && { ok=0; err="${err:+$err; }banner timeout"; }
    [ -z "$ssh_ms" ]   && { ok=0; err="${err:+$err; }ssh roundtrip failed"; }
    [ "$ok" = 0 ] && any_fail=1

    # values are numbers or fixed strings; $err is built in this script and
    # contains no quotes, so the JSON line is safe as-is.
    printf '{"ts":"%s","target":"%s","probe_host":"%s","tcp_ms":%s,"banner_ms":%s,"ssh_ms":%s,"ok":%s,"error":"%s"}\n' \
        "$(LC_ALL=C date -u '+%Y-%m-%dT%H:%M:%SZ')" "$name" "$bhost" \
        "${tcp:-null}" "${banner_ms:-null}" "${ssh_ms:-null}" "$ok" "$err" \
        >> "$LOG_FILE"

    fails_file="$STATE_DIR/$name.fails"
    alerted_file="$STATE_DIR/$name.alerted"
    if [ "$ok" = 0 ]; then
        fails=$(( $(cat "$fails_file" 2>/dev/null || echo 0) + 1 ))
        echo "$fails" >"$fails_file"
        if [ "$fails" -ge "$ALERT_AFTER" ] && [ ! -f "$alerted_file" ]; then
            emit_event warn "ssh to $name failed $fails consecutive probes: $err (tcp=${tcp:-fail}ms banner=${banner_ms:-fail}ms)"
            : >"$alerted_file"
        fi
    else
        if [ -f "$alerted_file" ]; then
            emit_event info "ssh to $name recovered (ssh roundtrip ${ssh_ms}ms)"
            pull_incident "$name" "$t"
        fi
        rm -f "$alerted_file"; echo 0 >"$fails_file"
    fi
done

tail -n 10000 "$LOG_FILE" >"$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
exit "$any_fail"
