#!/usr/bin/env bash
set -euo pipefail

ACTION=${ACTION:-status}
PROFILE=${PROFILE:-mcp-suite}
SERVICE=${SERVICE:-}
SERVICES=${SERVICES:-}

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

profile_args=()
if [[ -n "${PROFILE:-}" ]]; then
  # Allow multiple profiles via a space-separated list.
  # Example: PROFILE="mcp-suite gpu"
  read -r -a profiles <<< "$PROFILE"
  for p in "${profiles[@]}"; do
    if [[ -n "$p" ]]; then
      profile_args+=(--profile "$p")
    fi
  done
fi

service_args=()
if [[ -n "${SERVICES:-}" ]]; then
  # Allow multiple services via a space-separated list.
  # Example: SERVICES="caddy mcp-rag mcp-cuda"
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
