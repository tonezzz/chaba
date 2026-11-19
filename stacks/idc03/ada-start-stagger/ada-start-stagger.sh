#!/usr/bin/env bash
# ada-start-stagger.sh OFFSET_S — serialize mass ada-* service starts.
#
# kanban: idc03-stagger-ada-fleet-restarts-mass-re-ae9de7
# 2026-11-16 20:56:53 ICT: deploy-ada.sh issued one
# `systemctl --user restart` for the whole fleet; 6 pwa_server uvicorns
# (~615-750MB each) ramped in the same second -> ~3.7GB instant demand,
# load 11.8 on a 15GB/4-core box, dispatch load-gate starved ~30min.
#
# This ExecStartPre hook sleeps OFFSET_S only while OTHER ada-* start
# jobs are pending (a fleet transaction). A single-unit restart or
# crash-recovery sees <=1 pending start job and skips the delay.
set -u
OFFSET="${1:-0}"
case "$OFFSET" in ""|*[!0-9]*) OFFSET=0 ;; esac
[ "$OFFSET" -gt 0 ] 2>/dev/null || exit 0
pend=$(systemctl --user list-jobs --no-legend "ada-*.service" 2>/dev/null \
       | grep -cE "[[:space:]]start[[:space:]]")
case "$pend" in ""|*[!0-9]*) pend=0 ;; esac
[ "$pend" -gt 1 ] || exit 0
sleep "$OFFSET"
exit 0
