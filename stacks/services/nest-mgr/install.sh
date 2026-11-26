#!/usr/bin/env bash
# install.sh [host ...] — install + start nest-mgr on each host.
# Default hosts: the currently deployed fleet — idc02 idc03 con01 mn01
# tony-omen tony-macbook (tony-dell retired to omen 2026-10-19/20 phase-5;
# tony-macbook added 2026-11-17 via ops-macbook-nestmgr-install).
# v2 rollout: upgrade lands in monitor mode everywhere; flip a pilot host
# to recommend with `ssh <h> 'echo recommend > ~/.local/share/nest/mode'`.
# Installs the self-contained manager to ~/.local/share/nest/ and the user
# unit to ~/.config/systemd/user/ — no repo checkout is required on the
# target host.
set -euo pipefail
cd "$(dirname "$0")"
HOSTS=("$@")
[ ${#HOSTS[@]} -eq 0 ] && HOSTS=(idc02 idc03 con01 mn01 tony-omen tony-macbook)

for host in "${HOSTS[@]}"; do
  echo "== $host"
  if [ "$host" = "$(hostname)" ] || [ "$host" = "localhost" ]; then
    mkdir -p ~/.local/share/nest ~/.config/systemd/user
    install -m 0755 nest-mgr.py ~/.local/share/nest/nest-mgr.py
    install -m 0644 nest-mgr.service ~/.config/systemd/user/nest-mgr.service
    systemctl --user daemon-reload
    systemctl --user enable nest-mgr.service
    systemctl --user restart nest-mgr.service
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" \
      'mkdir -p ~/.local/share/nest ~/.config/systemd/user'
    scp -q nest-mgr.py "$host:~/.local/share/nest/nest-mgr.py"
    scp -q nest-mgr.service "$host:~/.config/systemd/user/nest-mgr.service"
    ssh -o BatchMode=yes "$host" \
      'chmod 0755 ~/.local/share/nest/nest-mgr.py &&
       systemctl --user daemon-reload &&
       systemctl --user enable nest-mgr.service &&
       systemctl --user restart nest-mgr.service'
  fi
  echo "   installed + started"
done
