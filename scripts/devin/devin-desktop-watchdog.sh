#!/usr/bin/env bash
# devin-desktop-watchdog.sh — health monitor for devin-desktop
#
# Runs from cron every 10 min. Actions:
#   1. Kill renderers stuck above CPU threshold (original behavior).
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
CPU_PCT="${WATCHDOG_CPU_PCT:-50}"
CPU_HOLD_SECS="${WATCHDOG_CPU_HOLD_SECS:-10}"
RESTART_COOLDOWN_SECS=1800
mkdir -p "$(dirname "$LOG")" "$STATE_DIR"

log() { echo "$(date -Iseconds) $*" >>"$LOG"; }

notify() {
    command -v notify-send >/dev/null 2>&1 || return 0
    for sock in /tmp/.X11-unix/X*; do
        [ -S "$sock" ] || continue
        DISPLAY=":${sock##*X}" \
        XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" \
            notify-send "Devin watchdog" "$*" 2>/dev/null && return 0
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

# --- 1. stuck renderer killer ------------------------------------------------
for pid in $(pgrep -f "^${BIN} --type=renderer"); do
    cpu1=$(ps -p "$pid" -o %cpu= 2>/dev/null | awk '{print $1}')
    if awk -v c="${cpu1:-0}" -v t="$CPU_PCT" 'BEGIN {exit !(c > t)}'; then
        sleep "$CPU_HOLD_SECS"
        if kill -0 "$pid" 2>/dev/null; then
            cpu2=$(ps -p "$pid" -o %cpu= 2>/dev/null | awk '{print $1}')
            if awk -v c="${cpu2:-0}" -v t="$CPU_PCT" 'BEGIN {exit !(c > t)}'; then
                log "Killing stuck devin-desktop renderer $pid (cpu $cpu1 -> $cpu2)"
                kill -TERM "$pid" 2>/dev/null
            fi
        fi
    fi
done

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
                systemd-run --user --unit=devin-desktop env \
                    DISPLAY="$disp" \
                    XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority" \
                    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" \
                    /usr/bin/devin-desktop >/dev/null 2>&1
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
