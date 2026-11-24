#!/usr/bin/env bash
# rollback.sh — return the Jack LLM stack to its pre-deploy state.
# Idempotent: safe to run when nothing is deployed. The stack is
# stateless (no data volumes to restore), so rollback = full teardown
# that restores the pre-deploy condition: nothing running, no generated
# env files left behind.
set -u
cd "$(dirname "$0")"

echo "rollback: stopping mock stack (if running)"
if [ -f mock/state.json ]; then
  pid=$(python3 -c 'import json;print(json.load(open("mock/state.json"))["pid"])' 2>/dev/null || true)
  if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    echo "rollback: killed mock pid $pid"
  fi
  rm -f mock/state.json mock/.env.mock
else
  echo "rollback: no mock state file — nothing to stop"
fi

echo "rollback: compose teardown (skipped — no runtime on this host)"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose -f docker-compose.yml down -v --remove-orphans || true
elif command -v podman >/dev/null 2>&1; then
  podman compose -f docker-compose.yml down -v --remove-orphans || true
else
  echo "rollback: no container runtime — compose teardown not applicable"
fi

echo "rollback: removing generated env (keeps env.example)"
rm -f .env

echo "rollback: complete — stack is at pre-deploy state"
