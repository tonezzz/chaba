#!/usr/bin/env bash
set -euo pipefail

set -a
. "$HOME/.config/secrets/cline-kanban.env"
set +a

systemctl --user is-active \
  cline-kanban.service \
  cline-kanban-proxy.service \
  cline-kanban-network.service >/dev/null
unauth_status=$(curl -sS -o /dev/null -w "%{http_code}" \
  http://100.72.146.39:3484/)
test "$unauth_status" = "401"
curl -fsS --config <(printf 'user = "cline:%s"\n' "$CLINE_PROXY_PASSCODE") \
  -o /dev/null http://100.72.146.39:3484/
