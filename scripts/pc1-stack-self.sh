#!/usr/bin/env bash
set -euo pipefail

ACTION=${ACTION:-status}
PROFILE=${PROFILE:-mcp-suite}
SERVICE=${SERVICE:-}

REPO_ROOT=${MCP_DEVOPS_REPO_ROOT:-/workspaces/chaba}
COMPOSE_FILE=${COMPOSE_FILE:-"$REPO_ROOT/stacks/pc1-stack/docker-compose.yml"}
PROJECT=${PROJECT:-pc1-stack}

if [[ "$COMPOSE_FILE" != "$REPO_ROOT/stacks/pc1-stack/docker-compose.yml" ]]; then
  echo "Refusing to run: COMPOSE_FILE must be the pc1-stack compose file" >&2
  exit 2
fi

if [[ "$PROJECT" != "pc1-stack" ]]; then
  echo "Refusing to run: PROJECT must be pc1-stack" >&2
  exit 2
fi

base=(docker compose -f "$COMPOSE_FILE" --project-name "$PROJECT")

case "$ACTION" in
  status)
    "${base[@]}" ps
    ;;
  up)
    "${base[@]}" --profile "$PROFILE" up -d
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
    echo "Unknown ACTION=$ACTION (supported: status|up|down|restart-service)" >&2
    exit 2
    ;;
esac
