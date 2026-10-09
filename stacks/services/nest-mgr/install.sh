#!/usr/bin/env bash
# install.sh [host ...] — install + start nest-mgr on each host.
# Default hosts: idc03 tony-omen tony-dell (the card's starting set).
# Installs the self-contained manager to ~/.local/share/nest/ and the user
# unit to ~/.config/systemd/user/ — no repo checkout is required on the
# target host.
set -euo pipefail
cd "$(dirname "$0")"
HOSTS=("$@")
[ ${#HOSTS[@]} -eq 0 ] && HOSTS=(idc03 tony-omen tony-dell)

for host in "${HOSTS[@]}"; do
  echo "== $host"
  if [ "$host" = "$(hostname)" ] || [ "$host" = "localhost" ]; then
    mkdir -p ~/.local/share/nest ~/.config/systemd/user
    install -m 0755 nest-mgr.py ~/.local/share/nest/nest-mgr.py
    install -m 0644 nest-mgr.service ~/.config/systemd/user/nest-mgr.service
    systemctl --user daemon-reload
    systemctl --user enable --now nest-mgr.service
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" \
      'mkdir -p ~/.local/share/nest ~/.config/systemd/user'
    scp -q nest-mgr.py "$host:~/.local/share/nest/nest-mgr.py"
    scp -q nest-mgr.service "$host:~/.config/systemd/user/nest-mgr.service"
    ssh -o BatchMode=yes "$host" \
      'chmod 0755 ~/.local/share/nest/nest-mgr.py &&
       systemctl --user daemon-reload &&
       systemctl --user enable --now nest-mgr.service'
  fi
  echo "   installed + started"
done
