#!/bin/bash
set -euo pipefail

APP_ROOT="/workspace/sites/dev-host"
APP_LOG="/tmp/dev-host.log"
GLAMA_ROOT="/workspace/sites/a1-idc1/api/glama"
GLAMA_LOG="/tmp/glama-api.log"
GLAMA_PORT="${GLAMA_PORT:-4020}"
AGENTS_ROOT="/workspace/sites/a1-idc1/api/agents"
AGENTS_LOG="/tmp/agents-api.log"
AGENTS_PORT="${AGENTS_PORT:-4060}"
PUBLISH_TOKEN_FILE="/workspace/.secrets/dev-host/publish.token"
DEV_HOST_ENV_FILE="/workspace/sites/dev-host/.env.dev-host"

if [ -z "${DEV_HOST_PUBLISH_TOKEN:-}" ] && [ -f "$PUBLISH_TOKEN_FILE" ]; then
  export DEV_HOST_PUBLISH_TOKEN="$(tr -d '\r\n' < "$PUBLISH_TOKEN_FILE")"
fi

if [ -f "$DEV_HOST_ENV_FILE" ]; then
  set -a
  CLEAN_ENV_FILE="$(mktemp)"
  tr -d '\r' < "$DEV_HOST_ENV_FILE" | sed '1s/^\xEF\xBB\xBF//' > "$CLEAN_ENV_FILE"
  . "$CLEAN_ENV_FILE"
  rm -f "$CLEAN_ENV_FILE"
  set +a
fi

log() {
  printf '[dev-host] %s\n' "$*"
}

ensure_glama() {
  if [ ! -d "$GLAMA_ROOT" ] || [ ! -f "$GLAMA_ROOT/package.json" ]; then
    log "glama sources not found at $GLAMA_ROOT"
    return 1
  fi

  cd "$GLAMA_ROOT"

  if [ ! -d node_modules ]; then
    log "[glama] node_modules missing; running npm install"
    npm install --silent --no-progress || log "[glama] npm install failed"
  fi

  log "[glama] starting backend on port $GLAMA_PORT"
  PORT="$GLAMA_PORT" node src/server.js >>"$GLAMA_LOG" 2>&1 &
  GLAMA_PID=$!
  log "[glama] pid $GLAMA_PID"
}

ensure_agents() {
  if [ ! -d "$AGENTS_ROOT" ] || [ ! -f "$AGENTS_ROOT/package.json" ]; then
    log "agents sources not found at $AGENTS_ROOT"
    return 1
  fi

  cd "$AGENTS_ROOT"

  if [ ! -d node_modules ]; then
    log "[agents] node_modules missing; running npm install"
    npm install --silent --no-progress || log "[agents] npm install failed"
  fi

  log "[agents] starting backend on port $AGENTS_PORT"
  PORT="$AGENTS_PORT" node src/server.js >>"$AGENTS_LOG" 2>&1 &
  AGENTS_PID=$!
  log "[agents] pid $AGENTS_PID"
}

ensure_gateway() {
  if [ ! -d "$APP_ROOT" ] || [ ! -f "$APP_ROOT/package.json" ]; then
    log "gateway sources not found at $APP_ROOT"
    return 1
  fi

  cd "$APP_ROOT"

  if [ ! -d node_modules ]; then
    log "node_modules missing; running npm install"
    npm install --silent --no-progress || log "npm install failed"
  fi

  export PORT="${PORT:-3000}"
  log "starting gateway on port $PORT"
  node src/server.js >>"$APP_LOG" 2>&1 &
  APP_PID=$!
  log "gateway pid $APP_PID"
}

shutdown() {
  log "received shutdown signal"
  kill -TERM "$SSHD_PID" 2>/dev/null || true
  if [ -n "${GLAMA_PID:-}" ]; then
    kill -TERM "$GLAMA_PID" 2>/dev/null || true
  fi
  if [ -n "${AGENTS_PID:-}" ]; then
    kill -TERM "$AGENTS_PID" 2>/dev/null || true
  fi
  if [ -n "${APP_PID:-}" ]; then
    kill -TERM "$APP_PID" 2>/dev/null || true
  fi
}

trap shutdown TERM INT

log "launching sshd"
/usr/sbin/sshd -D &
SSHD_PID=$!

APP_PID=""
GLAMA_PID=""
AGENTS_PID=""
ensure_glama || true
ensure_agents || true
ensure_gateway || true

WAIT_PIDS=("$SSHD_PID")
if [ -n "${GLAMA_PID:-}" ]; then
  WAIT_PIDS+=("$GLAMA_PID")
fi
if [ -n "${AGENTS_PID:-}" ]; then
  WAIT_PIDS+=("$AGENTS_PID")
fi
if [ -n "${APP_PID:-}" ]; then
  WAIT_PIDS+=("$APP_PID")
fi

wait "$SSHD_PID"
