#!/usr/bin/env bash
# container-suite-run.sh — ENTRYPOINT for the scenario quadlets
# (ada-scenario-smoke, ada-scenario-full). Applies the OPS-0581 exit-code
# contract to scenario-report.py, which exits 1 whenever a COMPLETED
# suite found failures. The quadlets bypass scenario-suite-run.sh (the
# .service suites' host wrapper), so findings were leaking into the exit
# code and red-alerting the timer-sentinel — seen 2026-11-08 10:37 when
# the bench $2 LiteLLM cap crossed mid-run: 20 fails + outage sentinel,
# completed run, exit 1, Failed result='exit-code'.
# Contract (docs/kb/timer-expectations.md): exit 0 on any run that
# reaches scenario-report.py's final report marker — the
# "  <N> scenarios: name=status, ..." summary printed only at the end of
# main(). exit 1 without it stays nonzero (real crash).
set -u
LOG="$(mktemp -t scenario-report.XXXXXX)"
python /app/scripts/scenario-report.py "$@" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
if [ "$rc" -eq 1 ] && grep -qE '^[0-9]+ scenarios:' "$LOG"; then
    rm -f "$LOG"
    echo "suite completed with failing scenarios — findings in the ops report store (exit 0)"
    exit 0
fi
rm -f "$LOG"
exit "$rc"
