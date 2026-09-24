#!/usr/bin/env bash
# Install ada-scenario-runner on the Ada host (idc01):
#   build image -> install quadlets -> daemon-reload.
# On-demand only — no timer. Run:
#   systemctl --user start ada-scenario-smoke
#   systemctl --user start ada-scenario-full
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

podman build -t localhost/ada-scenario-runner:latest "$HERE"
mkdir -p ~/.config/containers/systemd
cp "$HERE"/ada-scenario-*.container ~/.config/containers/systemd/
systemctl --user daemon-reload
echo "installed — run: systemctl --user start ada-scenario-smoke|full"
