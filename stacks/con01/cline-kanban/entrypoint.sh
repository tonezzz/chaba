#!/bin/sh
set -eu

case "${CLINE_ROLE:-}" in
  app)
    exec kanban --host 127.0.0.1 --port 3485 --no-open
    ;;
  proxy)
    exec node /opt/cline-kanban/proxy.mjs
    ;;
  *)
    echo "CLINE_ROLE must be app or proxy" >&2
    exit 64
    ;;
esac
