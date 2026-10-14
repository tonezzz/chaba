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
# Benchmark codes: 0=all pass, 1=scenario failures/policy violations,
# 2=lock contention/usage error. Per docs/kb/timer-expectations.md the
# unit exits 0 on any COMPLETED run — findings live in
# ada-ha-scenario-reports + the auto-report page, not the exit code.
# A completed run is detected by the final report marker "**Score:" the
# benchmark prints only when it runs to the end; exit 1 without it is a
# real crash and stays nonzero. Total run is bounded by TimeoutStartSec.
# Card: fix-scenario-schedule-collision.
set -u
SUITE="${1:?usage: scenario-suite-run.sh <suite>}"
LOCK_PORT=8199
BENCH="$HOME/CascadeProjects/ada-voice/scripts/scenario-benchmark.py"
PY="$HOME/CascadeProjects/ada-voice/.venv/bin/python"

# Paid-lane guard (card bench-off-paid-lanes, 2026-10-14): automated
# suites run on FREE dev lanes only — ada-dev :8005 / ada-kk-dev :8009.
# The prod persona lanes (:8001 ada-pi-pwa, :8002 ada-ha-tony, :8003
# ada-ha-michael, :8007 ada-kk) bill per-persona paid Gemini keys; a
# suite may target them only when a card explicitly asks (release s4/s5
# prod verification): drop a sentinel file
#   $SENTINEL_DIR/prod-allow-<suite>   (first line = card id)
# and the run consumes it (one-shot). Any other/unknown target is
# treated as paid — a new lane is parked until classified here.
SENTINEL_DIR="${ADA_SCENARIO_STATE:-$HOME/.local/share/ada-scenario-runner}"
SENTINEL="$SENTINEL_DIR/prod-allow-$SUITE"
url="${ADA_LIVE_URL:-}"
port="${url##*:}"; port="${port%%/*}"
case " $port " in
  *" 8005 "*|*" 8009 "*) ;;                      # free dev lanes — proceed
  *)
    if [ -f "$SENTINEL" ]; then
        card="$(head -n1 "$SENTINEL" | tr -d '[:space:]')"
        rm -f "$SENTINEL"
        echo "prod-lane run for suite $SUITE authorized by card " \
             "${card:-unknown} — sentinel consumed (one-shot)"
    else
        echo "suite $SUITE targets a paid lane " \
             "(${ADA_LIVE_URL:-unset — benchmark default :8002}) — parked, " \
             "zero sessions opened (bench-off-paid-lanes)."
        echo "  to authorize one prod run:  echo <card-id> > $SENTINEL"
        echo "  to retarget to dev lane:    ADA_LIVE_URL=ws://127.0.0.1:8005/ws"
        exit 0
    fi ;;
esac

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
    LOG="$(mktemp -t scenario-suite-run.XXXXXX)"
    "$PY" "$BENCH" --suite "$SUITE" 2>&1 | tee "$LOG"
    rc=${PIPESTATUS[0]}
    if [ "$rc" -eq 1 ] && grep -q '\*\*Score:' "$LOG"; then
        rm -f "$LOG"
        echo "suite completed with failing scenarios — findings in ada-ha-scenario-reports + auto-report page (exit 0)"
        exit 0
    fi
    rm -f "$LOG"
    [ "$rc" -eq 2 ] || exit "$rc"
    echo "lost :$LOCK_PORT bind race - re-queuing (attempt $attempt/8)"
done
echo "suite never won :$LOCK_PORT in 8 passes - giving up"
exit 2
