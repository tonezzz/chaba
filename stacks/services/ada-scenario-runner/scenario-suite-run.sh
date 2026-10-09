#!/usr/bin/env bash
# scenario-suite-run.sh <suite> — wrapper around scenario-benchmark.py that
# turns the suite lock (:8199, TCP bind+listen) into a queue instead of a
# drop:
#   * wait up to 30 min per pass for the port to become bindable (holder =
#     another scenario suite or the hourly smoke tier). Probe = an actual
#     bind — the same test the benchmark itself makes (a connect-probe is
#     unreliable here: backlog-1 listeners can refuse new connects).
#   * a refused bind (exit 2) re-enters the wait — simultaneous starters
#     (e.g. persistent timers making up missed slots on boot) can all see
#     the port free in the same second and race the bind.
# Real results (0=pass / 1=scenario failures, the test signal) pass through
# unchanged. Total run is bounded by the unit's TimeoutStartSec.
# Card: fix-scenario-schedule-collision.
set -u
SUITE="${1:?usage: scenario-suite-run.sh <suite>}"
LOCK_PORT=8199
BENCH="$HOME/CascadeProjects/ada-pi/scripts/scenario-benchmark.py"
PY="$HOME/CascadeProjects/ada-pi/.venv/bin/python"

free() {
    "$PY" -c 'import socket,sys
s=socket.socket()
try: s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError: sys.exit(1)' "$LOCK_PORT" >/dev/null 2>&1
}

attempt=0
while [ "$attempt" -lt 8 ]; do
    attempt=$((attempt + 1))
    for i in $(seq 30); do
        free && break
        echo "scenario lock :$LOCK_PORT held - waiting $i/30 (pass $attempt)"
        sleep 60
    done
    free || { echo "scenario lock :$LOCK_PORT held >30m - abandoning this slot"; exit 1; }
    "$PY" "$BENCH" --suite "$SUITE"
    rc=$?
    [ "$rc" -eq 2 ] || exit "$rc"
    echo "lost :$LOCK_PORT bind race - re-queuing (attempt $attempt/8)"
done
echo "suite never won :$LOCK_PORT in 8 passes - giving up"
exit 2
