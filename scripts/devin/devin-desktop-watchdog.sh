#!/usr/bin/env bash
# devin-desktop-watchdog.sh — health monitor for devin-desktop
#
# Runs from cron every 10 min. Actions:
#   1. Kill renderers only when wedged: interval CPU (measured during a
#      10s hold, NOT ps lifetime-average) above threshold across several
#      consecutive runs (~30 min) with a startup grace period — legit
#      busy renderers (indexing, agent sessions, scan jobs) are left alone.
#      WATCHDOG_RENDERER_KILL=0 in ~/.config/devin/watchdog.conf keeps the
#      detection + heads-up notification but never kills.
#   1b. Escalate a hung window: a killed/wedged renderer can leave
#      Electron's modal "The window is not responding" dialog, which
#      ignores synthetic input (pointer grab). If a modal window named
#      "Devin" persists across runs (or appears right after a renderer
#      kill), the whole app is TERM'd so the dead-app path below restarts
#      it — that is the only reliable recovery (observed 2026-09-22).
#   2. If the main devin-desktop process is gone, clean up orphaned
#      app-devin-desktop-*.scope units and tool-spawned children
#      (headless Chrome, probes) that keep burning CPU after a crash.
#   3. Detect new AppArmor userns denials and renderer crashes in the
#      journal and log + desktop-notify them (once per event).
#   4. Optional auto-restart: create ~/.config/devin/watchdog-autorestart
#      to enable; relaunches on the first X display it finds, with a
#      30-minute cooldown.
#
# Install: scripts/devin/install-devin-host.sh

LOG="$HOME/.local/share/devin/cli/watchdog.log"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/devin-watchdog"
BIN="/usr/share/devin-desktop/devin-desktop"
CPU_PCT=95
CPU_HOLD_SECS=10
HOT_RUNS=3
RENDERER_KILL=1
RESTART_COOLDOWN_SECS=1800
HANG_RUNS=2
# Per-host overrides: WATCHDOG_CPU_PCT, WATCHDOG_CPU_HOLD_SECS,
# WATCHDOG_HOT_RUNS, WATCHDOG_RENDERER_KILL (0 = detect+notify only,
# never kill — right choice for the primary workstation),
# WATCHDOG_HANG_RUNS (consecutive runs with the modal hang dialog before
# the app is restarted; 0 disables hang escalation).
[ -f "$HOME/.config/devin/watchdog.conf" ] && . "$HOME/.config/devin/watchdog.conf"
CPU_PCT="${WATCHDOG_CPU_PCT:-$CPU_PCT}"
CPU_HOLD_SECS="${WATCHDOG_CPU_HOLD_SECS:-$CPU_HOLD_SECS}"
HOT_RUNS="${WATCHDOG_HOT_RUNS:-$HOT_RUNS}"
RENDERER_KILL="${WATCHDOG_RENDERER_KILL:-$RENDERER_KILL}"
HANG_RUNS="${WATCHDOG_HANG_RUNS:-$HANG_RUNS}"
mkdir -p "$(dirname "$LOG")" "$STATE_DIR"

log() { echo "$(date -Iseconds) $*" >>"$LOG"; }

notify() {
    command -v notify-send >/dev/null 2>&1 || return 0
    for sock in /tmp/.X11-unix/X*; do
        [ -S "$sock" ] || continue
        # timeout: notify-send can block indefinitely when the notification
        # daemon is wedged (observed right after a seat-session restart).
        DISPLAY=":${sock##*X}" \
        XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" \
            timeout 5 notify-send "Devin watchdog" "$*" 2>/dev/null && return 0
    done
    return 0
}

# Main GUI process = cmdline starting with $BIN but not a child type
# (--type=renderer/gpu/utility/...), not the cli.js launcher, not crashpad.
# Deliberately NOT anchored at end: a GUI launched with flags (e.g.
# --no-sandbox) still counts as the main process.
main_pid() {
    local p args
    for p in $(pgrep -f "^${BIN}" 2>/dev/null); do
        args=$(tr '\0' ' ' <"/proc/$p/cmdline" 2>/dev/null) || continue
        case "$args" in
            *--type=*|*cli.js*|*crashpad*) continue ;;
        esac
        echo "$p"
        return 0
    done
    # Fallback: Devin's own single-instance lock holds the GUI main PID.
    if [ -f "$HOME/.config/Devin/code.lock" ]; then
        p=$(cat "$HOME/.config/Devin/code.lock" 2>/dev/null)
        case "$p" in ''|*[!0-9]*) return 1 ;; esac
        kill -0 "$p" 2>/dev/null && { echo "$p"; return 0; }
    fi
    return 1
}

# Find Electron's modal "The window is not responding" dialog: a window
# named exactly "Devin" carrying _NET_WM_STATE_MODAL. Prints the window id
# on the first match across all X sockets, else nothing.
hang_dialog() {
    local sock disp xa w
    xa="/run/user/$(id -u)/gdm/Xauthority"
    for sock in /tmp/.X11-unix/X*; do
        [ -S "$sock" ] || continue
        disp=":${sock##*X}"
        for w in $(DISPLAY="$disp" XAUTHORITY="$xa" timeout 5 \
                   xdotool search --name "^Devin$" 2>/dev/null); do
            if DISPLAY="$disp" XAUTHORITY="$xa" \
               xprop -id "$w" _NET_WM_STATE 2>/dev/null \
               | grep -q _NET_WM_STATE_MODAL; then
                echo "$w"
                return 0
            fi
        done
    done
    return 1
}

# --- 1. wedged renderer detection (+ optional kill) ---------------------------
# Detection always runs: a renderer >=2 min old whose *interval* CPU (times
# delta measured over CPU_HOLD_SECS, not the ps lifetime average which stays
# elevated long after a busy renderer settles) stays above CPU_PCT for a run
# is logged and notified once. It is only killed if it stays pegged for
# HOT_RUNS consecutive runs (~10 min apart) AND WATCHDOG_RENDERER_KILL=1.
# Killing a legit busy renderer presents as a crash dialog to the user, so the
# bar is deliberately high; on the primary workstation set RENDERER_KILL=0.
HOT_FILE="$STATE_DIR/hot-renderers"
declare -A SEEN RUNS
if [ -f "$HOT_FILE" ]; then
    while read -r p t r; do SEEN[$p]=$t; RUNS[$p]=${r:-1}; done <"$HOT_FILE"
fi
: >"$HOT_FILE.new"
KILLED_RENDERER=0
now=$(date +%s)
for pid in $(pgrep -f "^${BIN} --type=renderer"); do
    etimes=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')
    [ "${etimes:-0}" -lt 120 ] && continue   # startup grace
    t1=$(ps -o times= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -n "$t1" ] || continue
    sleep "$CPU_HOLD_SECS"
    t2=$(ps -o times= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -n "$t2" ] || continue   # exited during the hold
    cpu=$(awk -v d="$((t2 - t1))" -v h="$CPU_HOLD_SECS" \
          'BEGIN {printf "%.1f", d * 100 / h}')
    awk -v c="$cpu" -v t="$CPU_PCT" 'BEGIN {exit !(c >= t)}' || continue
    runs=$(( ${RUNS[$pid]:-0} + 1 ))
    if [ "$RENDERER_KILL" = "1" ] && [ "$runs" -ge "$HOT_RUNS" ]; then
        log "Killing wedged devin-desktop renderer $pid (hot since $(date -d "@${SEEN[$pid]}" -Iseconds), $runs runs, interval cpu $cpu%)"
        notify "Devin renderer $pid wedged (>${CPU_PCT}% CPU for ~$((HOT_RUNS * 10)) min) — killed"
        kill -TERM "$pid" 2>/dev/null
        KILLED_RENDERER=1
    else
        echo "$pid ${SEEN[$pid]:-$now} $runs" >>"$HOT_FILE.new"
        log "Renderer $pid hot (interval cpu $cpu% >= ${CPU_PCT}%, run $runs/$HOT_RUNS, kill=$RENDERER_KILL)"
        if [ "$runs" -eq 1 ]; then
            if [ "$RENDERER_KILL" = "1" ]; then
                notify "Devin renderer $pid busy (${cpu}% CPU) — will be killed if still pegged in ~$((HOT_RUNS * 10)) min"
            else
                notify "Devin renderer $pid busy (${cpu}% CPU, kill disabled)"
            fi
        fi
    fi
done
mv "$HOT_FILE.new" "$HOT_FILE"

# --- 1b. hung-window escalation ----------------------------------------------
# A wedged (or just-killed) renderer can leave Electron's modal "The window
# is not responding" dialog. It ignores synthetic clicks/keys (pointer grab)
# and the app never recovers on its own — the only fix is restarting the
# app, after which the dead-app path below cleans up and auto-restarts.
# Escalate when we just killed a renderer and the dialog is already up, or
# when the dialog persists across HANG_RUNS consecutive runs (~20 min).
HANG_STATE="$STATE_DIR/hang-dialog-runs"
if [ "$HANG_RUNS" -gt 0 ]; then
    [ "$KILLED_RENDERER" = "1" ] && sleep 15   # let Electron react to the kill
    hang_win=$(hang_dialog || true)
    if [ -n "$hang_win" ]; then
        hruns=$(( $(cat "$HANG_STATE" 2>/dev/null || echo 0) + 1 ))
        echo "$hruns" >"$HANG_STATE"
        if [ "$KILLED_RENDERER" = "1" ] || [ "$hruns" -ge "$HANG_RUNS" ]; then
            mp=$(main_pid || true)
            log "Devin window unresponsive (modal dialog $hang_win, run $hruns) — TERMing main pid ${mp:-none}; dead-app path will recover"
            notify "Devin window hung — restarting app"
            [ -n "$mp" ] && kill -TERM "$mp" 2>/dev/null
            sleep 5
        else
            log "Devin modal hang dialog present (win $hang_win, run $hruns/$HANG_RUNS) — waiting"
            notify "Devin window not responding — will restart if still hung next check"
        fi
    else
        rm -f "$HANG_STATE"
    fi
fi

# --- 2. orphan cleanup when the main process is dead -------------------------
if ! main_pid >/dev/null || [ -z "$(main_pid)" ]; then
    orphans=0
    while read -r scope _; do
        [ -n "$scope" ] || continue
        log "Stopping orphaned scope $scope (devin-desktop main process is gone)"
        systemctl --user stop "$scope" 2>/dev/null
        orphans=$((orphans + 1))
    done < <(systemctl --user list-units --type=scope --state=active \
                 --no-legend 'app-devin-desktop-*' 2>/dev/null)

    # Tool-spawned children that outlive the app (headless browser, probes).
    # Recheck first: a fresh instance may have just started (race guard).
    if ! main_pid >/dev/null || [ -z "$(main_pid)" ]; then
        pkill -f 'user-data-dir=/tmp/chrome-devtools-profile' 2>/dev/null
        pkill -f "^${BIN} --type=" 2>/dev/null
    fi
    [ "$orphans" -gt 0 ] && notify "Devin crashed; cleaned $orphans orphaned scope(s)."

    # --- 4. optional auto-restart ---------------------------------------------
    if [ -f "$HOME/.config/devin/watchdog-autorestart" ]; then
        last=$(cat "$STATE_DIR/last-restart" 2>/dev/null || echo 0)
        now=$(date +%s)
        if [ $((now - last)) -ge "$RESTART_COOLDOWN_SECS" ]; then
            for sock in /tmp/.X11-unix/X*; do
                [ -S "$sock" ] || continue
                disp=":${sock##*X}"
                log "Auto-restarting devin-desktop on DISPLAY=$disp"
                # nohup+setsid, not systemd-run: transient-service launches were
                # observed dying ~1.3s in on tony-omen (2026-09-21).
                env DISPLAY="$disp" \
                    XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority" \
                    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" \
                    setsid /usr/bin/devin-desktop \
                    >>"$HOME/.local/share/devin/cli/devin-restart-watchdog.log" \
                    2>&1 </dev/null &
                echo "$now" >"$STATE_DIR/last-restart"
                notify "Devin desktop auto-restarted on DISPLAY=$disp"
                break
            done
        fi
    fi
fi

# --- 3. journal signatures: apparmor denials + renderer crashes ---------------
seen_file="$STATE_DIR/seen-journal"
last_seen=$(cat "$seen_file" 2>/dev/null || echo 0)
now=$(date +%s)
# Cap the lookback: never scan more than the last 15 min (first run -> now-900).
case "$last_seen" in ''|*[!0-9]*) last_seen=0 ;; esac
[ "$last_seen" -lt $((now - 900)) ] && last_seen=$((now - 900))

hits=$(journalctl --since "@${last_seen}" --no-pager -o cat 2>/dev/null |
    grep -aE 'apparmor="DENIED".*devin-desktop|renderer process gone' | sort -u)
if [ -n "$hits" ]; then
    while IFS= read -r line; do
        log "ALERT: $line"
    done <<<"$hits"
    notify "Devin: $(echo "$hits" | head -1 | cut -c1-80)"
fi
echo "$now" >"$seen_file"
