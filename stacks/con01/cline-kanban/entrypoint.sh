#!/bin/sh
set -eu

case "${CLINE_ROLE:-}" in
  app)
    exec kanban --host 0.0.0.0 --port 3485 --no-open --no-passcode
    ;;
  proxy)
    exec node /opt/cline-kanban/proxy.mjs
    ;;
  *)
    echo "CLINE_ROLE must be app or proxy" >&2
    exit 64
    ;;
esac
