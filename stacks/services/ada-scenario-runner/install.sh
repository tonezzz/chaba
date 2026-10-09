#!/usr/bin/env bash
# Install ada-scenario-runner on the Ada host (idc03):
#   build image -> install quadlets + units -> daemon-reload -> arm timers.
# Schedule (all times local, Asia/Bangkok):
#   ada-scenario-smoke.timer      hourly :00 (self-skips when :8199 held)
#   ada-bench-casting.timer       daily 02:00 -> OnSuccess runs casting suite
#   ada-scenario-{research,cms,memory,reports,tools}.timer  Mon-Fri 05:55
#   ada-scenario-casting.timer    Sat 05:55
#   ada-embed-bench.timer         Sat 06:00
# Weekly suites queue behind the :8199 suite lock (ExecStartPre, <=30 min)
# instead of refusing — see card fix-scenario-schedule-collision.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

podman build -t localhost/ada-scenario-runner:latest "$HERE"
mkdir -p ~/.config/containers/systemd ~/.config/systemd/user \
         ~/.local/share/ada-scenario-runner
# Wrapper runs self-contained from ~/.local/share (like log-shipper) — a
# stale/divergent repo checkout must never break the weekly suites.
install -m 0755 "$HERE/scenario-suite-run.sh" \
    ~/.local/share/ada-scenario-runner/scenario-suite-run.sh
cp "$HERE"/ada-scenario-*.container ~/.config/containers/systemd/
cp "$HERE"/ada-scenario-*.service "$HERE"/ada-scenario-*.timer \
   "$HERE"/ada-bench-casting.service "$HERE"/ada-bench-casting.timer \
   "$HERE"/ada-embed-bench.service "$HERE"/ada-embed-bench.timer \
   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now \
    ada-scenario-smoke.timer \
    ada-scenario-research.timer \
    ada-scenario-cms.timer \
    ada-scenario-memory.timer \
    ada-scenario-reports.timer \
    ada-scenario-tools.timer \
    ada-scenario-casting.timer \
    ada-bench-casting.timer \
    ada-embed-bench.timer
echo "installed — timers: systemctl --user list-timers | grep -E 'scenario|bench'"
