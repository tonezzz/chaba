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
#
# Logs:   $CPU_JOB_LOG_DIR/<name>-<UTC timestamp>.log
# Status: $CPU_JOB_LOG_DIR/<name>.status (append-only: started/finished lines)
# Exit:   the wrapped command's exit code.

set -euo pipefail

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
