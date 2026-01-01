#!/usr/bin/env bash
set -euo pipefail

STACK=${STACK:-pc1-stack}
ACTION=${ACTION:-status}
PROFILE=${PROFILE:-}
SERVICE=${SERVICE:-}
SERVICES=${SERVICES:-}

REPO_ROOT=${MCP_DEVOPS_REPO_ROOT:-/workspaces/chaba}
STACK_DIR="$REPO_ROOT/stacks/$STACK"
COMPOSE_FILE=${COMPOSE_FILE:-"$STACK_DIR/docker-compose.yml"}
PROJECT=${PROJECT:-$STACK}

if [[ ! -d "$STACK_DIR" ]]; then
  echo "stack dir not found: $STACK_DIR" >&2
  exit 2
fi

if [[ "$COMPOSE_FILE" != "$STACK_DIR/docker-compose.yml" ]]; then
  echo "Refusing to run: COMPOSE_FILE must equal $STACK_DIR/docker-compose.yml" >&2
  exit 2
fi

if [[ "$PROJECT" != "$STACK" ]]; then
  echo "Refusing to run: PROJECT must equal STACK ($STACK)" >&2
  exit 2
fi

base=(docker compose -f "$COMPOSE_FILE" --project-name "$PROJECT")

profile_args=()
if [[ -n "${PROFILE:-}" ]]; then
  read -r -a profiles <<< "$PROFILE"
  for p in "${profiles[@]}"; do
    if [[ -n "$p" ]]; then
      profile_args+=(--profile "$p")
    fi
  done
fi

service_args=()
if [[ -n "${SERVICES:-}" ]]; then
  read -r -a svc_list <<< "$SERVICES"
  for s in "${svc_list[@]}"; do
    if [[ -n "$s" ]]; then
      service_args+=("$s")
    fi
  done
fi

case "$ACTION" in
  status)
    "${base[@]}" ps
    ;;
  pull)
    "${base[@]}" pull
    ;;
  up)
    "${base[@]}" "${profile_args[@]}" up -d "${service_args[@]}"
    ;;
  pull-up)
    "${base[@]}" pull
    "${base[@]}" "${profile_args[@]}" up -d "${service_args[@]}"
    ;;
  down)
    "${base[@]}" down
    ;;
  restart-service)
    if [[ -z "$SERVICE" ]]; then
      echo "Missing SERVICE for ACTION=restart-service" >&2
      exit 2
    fi
    "${base[@]}" restart "$SERVICE"
    ;;
  *)
    echo "Unknown ACTION=$ACTION (supported: status|pull|up|pull-up|down|restart-service)" >&2
    exit 2
    ;;
esac
