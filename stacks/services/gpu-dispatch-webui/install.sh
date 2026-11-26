#!/usr/bin/env bash
# install.sh [host ...] — install + start gpu-dispatch-webui.
# Default host: idc02 (the dispatch control node — Redis, queue_manager.py,
# dispatch-scheduler all live there; the service binds the tailnet IP :8795).
#
# Layout on target:
#   /home/tony/ansible/webui/gpu_dispatch_webui.py   (this file's sibling)
#   /home/tony/ansible/webui/static/{index.html,app.css,app.js}
#   /home/tony/ansible/webui/audit.jsonl             (created on first mutation)
#   ~/.config/systemd/user/gpu-dispatch-webui.service
#
# Uses the existing ~/.local/venv-sidecar python (redis-py already present).
set -euo pipefail
cd "$(dirname "$0")"
HOSTS=("$@")
[ ${#HOSTS[@]} -eq 0 ] && HOSTS=(idc02)

for host in "${HOSTS[@]}"; do
  echo "== $host"
  if [ "$host" = "$(hostname -s 2>/dev/null || hostname)" ] || [ "$host" = "localhost" ]; then
    install -d -m 0755 /home/tony/ansible/webui/static
    install -m 0755 gpu_dispatch_webui.py /home/tony/ansible/webui/
    install -m 0644 static/index.html static/app.css static/app.js /home/tony/ansible/webui/static/
    install -m 0644 gpu-dispatch-webui.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now gpu-dispatch-webui.service
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" \
      'mkdir -p /home/tony/ansible/webui/static ~/.config/systemd/user'
    scp -q gpu_dispatch_webui.py "$host:/home/tony/ansible/webui/"
    scp -q static/index.html static/app.css static/app.js "$host:/home/tony/ansible/webui/static/"
    scp -q gpu-dispatch-webui.service "$host:~/.config/systemd/user/gpu-dispatch-webui.service"
    ssh -o BatchMode=yes "$host" 'chmod 0755 /home/tony/ansible/webui/gpu_dispatch_webui.py &&
      systemctl --user daemon-reload &&
      systemctl --user enable --now gpu-dispatch-webui.service'
  fi
  sleep 1
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" \
    'systemctl --user is-active gpu-dispatch-webui.service &&
     curl -sf -o /dev/null -w "  /api/state -> %{http_code}\n" http://100.123.163.11:8795/api/state' \
    || curl -sf -o /dev/null -w "  /api/state -> %{http_code}\n" http://100.123.163.11:8795/api/state
  echo "   installed + started on $host"
done
