#!/usr/bin/env bash
# run-cpu-job.sh — bounded, observable launcher for CPU-heavy one-off jobs.
#
# Replaces bare `nohup ... &` jobs that outlive their parent shell with no
# timeout, thread cap, or log path. The job runs in a transient user systemd
# scope inside cpu-jobs.slice (aggregate CPUQuota=600%, MemoryMax=16G), with a
# capped OMP thread count, a wall-clock timeout, and nice 10 so interactive
# work and services keep priority.
#
# Usage:
#   run-cpu-job.sh <job-name> <command> [args...]
#   CPU_JOB_THREADS=4 CPU_JOB_TIMEOUT=3600 run-cpu-job.sh rsd ./inference.py -i in.png
#
# Env overrides:
#   CPU_JOB_THREADS  OMP_NUM_THREADS per job            (default 6)
#   CPU_JOB_TIMEOUT  wall-clock seconds before TERM     (default 7200 = 2h)
#   CPU_JOB_NICE     nice level                         (default 10)
#   CPU_JOB_LOG_DIR  log/status directory               (default ~/var/log/cpu-jobs)
#   CPU_JOB_SLICE    systemd --user slice                (default cpu-jobs.slice)
#   CPU_JOB_TEMP_LIMIT   defer new jobs above this hottest-zone C (default 60)
#   CPU_JOB_TEMP_RESUME  clear the thermal hold at/below this C (default 55)
#   CPU_JOB_TEMP_CHECK=0  disable the thermal gate (e.g. sensorless VM)
#   CPU_JOB_TEMP_SYSFS    override thermal zone glob (tests / unusual hosts)
#   CHABA_THERMAL_CONFIG  Ansible-managed config (~/.config/chaba/thermal.env),
#                         sourced before these overrides are applied.
#
# Logs:   $CPU_JOB_LOG_DIR/<name>-<UTC timestamp>.log
# Status: $CPU_JOB_LOG_DIR/<name>.status (append-only: started/finished lines)
# Exit:   the wrapped command's exit code.

set -euo pipefail

# Thresholds live in one Ansible-managed file so they can be adjusted by
# re-running the playbook instead of editing every host's wrapper. Env vars
# still win for one-off overrides (and for the local test harness).
thermal_config="${CHABA_THERMAL_CONFIG:-$HOME/.config/chaba/thermal.env}"
if [ -r "$thermal_config" ]; then
    # shellcheck disable=SC1090
    . "$thermal_config"
fi

job_name="${1:?usage: run-cpu-job.sh <job-name> <command> [args...]}"
shift
(($#)) || { echo "run-cpu-job.sh: missing command" >&2; exit 2; }

# Unit names only allow these characters; refuse anything else early.
[[ "$job_name" =~ ^[A-Za-z0-9_.-]+$ ]] || {
    echo "run-cpu-job.sh: invalid job name '$job_name'" >&2
    exit 2
}

threads="${CPU_JOB_THREADS:-6}"
timeout_secs="${CPU_JOB_TIMEOUT:-7200}"
nice_level="${CPU_JOB_NICE:-10}"
log_dir="${CPU_JOB_LOG_DIR:-$HOME/var/log/cpu-jobs}"
slice="${CPU_JOB_SLICE:-cpu-jobs.slice}"

mkdir -p "$log_dir"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
unit="cpu-job-${job_name}-${ts}"
log="$log_dir/${job_name}-${ts}.log"
status="$log_dir/${job_name}.status"

# Thermal admission — always use the hottest zone (CPU package, GPU, WiFi,
# whichever reads highest) so a hot secondary sensor cannot be hidden by a
# cool CPU reading. Deny is sticky until the box has visibly cooled, so a
# borderline reading cannot re-admit work into an already-hot host.
_max_temp() {
    local peak="0" z raw v cmd flag out
    local zones="${CPU_JOB_TEMP_SYSFS:-/sys/class/thermal/thermal_zone*/temp}"
    for z in $zones; do
        [ -r "$z" ] || continue
        raw=$(cat "$z" 2>/dev/null) || continue
        case "$raw" in ''|*[!0-9]*) continue ;; esac
        v=$(awk -v v="$raw" 'BEGIN{printf "%.1f", v/1000}')
        awk -v v="$v" -v m="$peak" 'BEGIN{exit !(v>m)}' && peak="$v"
    done
    # No sysfs on macOS: smctemp reports both CPU and GPU unprivileged.
    if [ "$peak" = "0" ]; then
        for cmd in "$HOME/.local/bin/smctemp" "smctemp"; do
            command -v "$cmd" >/dev/null 2>&1 || continue
            for flag in -c -g; do
                out=$("$cmd" "$flag" 2>/dev/null | head -1)
                case "$out" in ''|*[!0-9.]*) continue ;; esac
                awk -v v="$out" -v m="$peak" 'BEGIN{exit !(v>m)}' && peak="$out"
            done
            break
        done
    fi
    [ "$peak" != "0" ] && echo "$peak"
}

if [ "${CPU_JOB_TEMP_CHECK:-1}" != "0" ]; then
    temp_limit="${CPU_JOB_TEMP_LIMIT:-60}"
    temp_resume="${CPU_JOB_TEMP_RESUME:-55}"
    temp_state="$log_dir/.thermal-cooldown"
    peak="$(_max_temp)"
    reason=""
    if [ -n "$peak" ] && awk -v v="$peak" -v l="$temp_limit" \
            'BEGIN{exit !(v>l)}'; then
        : >"$temp_state"
        reason="temp_high"
    elif [ -f "$temp_state" ]; then
        if [ -n "$peak" ] && awk -v v="$peak" -v l="$temp_resume" \
                'BEGIN{exit !(v<=l)}'; then
            rm -f "$temp_state"
        else
            reason="temp_cooldown"
        fi
    fi
    if [ -n "$reason" ]; then
        printf 'job=%s deferred=%s reason=%s max_temp_c=%s limit=%s host=%s\n' \
            "$job_name" "$(date -Is)" "$reason" "${peak:-unknown}" \
            "$temp_limit" "$(hostname)" >>"$status"
        echo "run-cpu-job.sh: deferred ($reason): hottest sensor ${peak:-unknown}C, limit ${temp_limit}C" >&2
        exit 75
    fi
fi

printf 'job=%s started=%s host=%s unit=%s slice=%s threads=%s timeout=%ss cmd=%q' \
    "$job_name" "$(date -Is)" "$(hostname)" "$unit" "$slice" \
    "$threads" "$timeout_secs" "$*" >>"$status"
printf '\n' >>"$status"

echo "run-cpu-job.sh: log -> $log"

# systemd-run keeps the job in a named cgroup inside the aggregate-capped
# slice; `timeout` is the actual wall-clock guard (scope units do not accept
# a runtime timeout).
systemd-run --user --scope --unit="$unit" --slice="$slice" \
    env OMP_NUM_THREADS="$threads" \
    nice -n "$nice_level" \
    timeout --signal=TERM --kill-after=60s "$timeout_secs" \
    "$@" 2>&1 | tee "$log"
rc="${PIPESTATUS[0]}"

printf 'job=%s finished=%s rc=%s log=%s\n' \
    "$job_name" "$(date -Is)" "$rc" "$log" >>"$status"
exit "$rc"
