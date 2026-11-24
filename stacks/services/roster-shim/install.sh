#!/usr/bin/env bash
# install.sh [host ...] — install + start roster-shim.
# Default host: idc03 (roster lanes live on the idc03 tailnet edge, next to
# the ada lanes and the devin CLI at ~/.local/bin/devin).
# Self-contained install to ~/.local/share/roster-shim/ (venv with
# websockets+pyyaml) — no repo checkout needed at runtime.
set -euo pipefail
cd "$(dirname "$0")"
HOSTS=("$@")
[ ${#HOSTS[@]} -eq 0 ] && HOSTS=(idc03)

payload() {  # runs on the target host
  set -e
  mkdir -p ~/.local/share/roster-shim ~/.config/systemd/user
  install -m 0755 roster-shim.py nest-ask.py lanes.yml \
    ~/.local/share/roster-shim/
  install -m 0644 roster-shim.service ~/.config/systemd/user/
  cd ~/.local/share/roster-shim
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/pip -q install "websockets>=14" pyyaml
  systemctl --user daemon-reload
  systemctl --user enable --now roster-shim.service
}

for host in "${HOSTS[@]}"; do
  echo "== $host"
  if [ "$host" = "$(hostname -s 2>/dev/null || hostname)" ] || [ "$host" = "localhost" ]; then
    payload
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" \
      'mkdir -p ~/.local/share/roster-shim ~/.config/systemd/user'
    scp -q roster-shim.py nest-ask.py lanes.yml \
      "$host:~/.local/share/roster-shim/"
    scp -q roster-shim.service \
      "$host:~/.config/systemd/user/roster-shim.service"
    ssh -o BatchMode=yes "$host" 'cd ~/.local/share/roster-shim &&
      install -m 0755 roster-shim.py nest-ask.py lanes.yml . &&
      [ -x .venv/bin/python ] || python3 -m venv .venv &&
      .venv/bin/pip -q install "websockets>=14" pyyaml &&
      systemctl --user daemon-reload &&
      systemctl --user enable --now roster-shim.service'
  fi
  echo "   installed + started"
done
