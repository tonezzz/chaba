#!/usr/bin/env bash
# install.sh [host ...] — install + start nest-io on each host.
# Default host: idc03 (the ada-pi-pwa / input-bridge host — the fabric
# sits next to the surfaces it routes between).
# Installs the self-contained daemon to ~/.local/share/nest/io-fabric/
# and the user unit to ~/.config/systemd/user/ — no repo checkout needed.
set -euo pipefail
cd "$(dirname "$0")"
HOSTS=("$@")
[ ${#HOSTS[@]} -eq 0 ] && HOSTS=(idc03)

for host in "${HOSTS[@]}"; do
  echo "== $host"
  if [ "$host" = "$(hostname)" ] || [ "$host" = "localhost" ]; then
    mkdir -p ~/.local/share/nest/io-fabric ~/.config/systemd/user
    install -m 0755 nest-io.py ~/.local/share/nest/io-fabric/nest-io.py
    install -m 0644 nest-io.service ~/.config/systemd/user/nest-io.service
    systemctl --user daemon-reload
    systemctl --user enable --now nest-io.service
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" \
      'mkdir -p ~/.local/share/nest/io-fabric ~/.config/systemd/user'
    scp -q nest-io.py "$host:~/.local/share/nest/io-fabric/nest-io.py"
    scp -q nest-io.service "$host:~/.config/systemd/user/nest-io.service"
    ssh -o BatchMode=yes "$host" \
      'chmod 0755 ~/.local/share/nest/io-fabric/nest-io.py &&
       systemctl --user daemon-reload &&
       systemctl --user enable --now nest-io.service'
  fi
  echo "   installed + started"
done
