#!/usr/bin/env bash
set -euo pipefail

trace_id="${1:-}"

compose_file="stacks/idc1-assistance/docker-compose.yml"
health_url="${JARVIS_HEALTH_URL:-http://127.0.0.1:18018/health}"

echo "[evidence] ts=$(date -Is)"
if [[ -n "${trace_id}" ]]; then
  echo "[evidence] trace_id=${trace_id}"
fi

if command -v git >/dev/null 2>&1; then
  echo "[evidence] git_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  echo "[evidence] git_sha=$(git rev-parse HEAD 2>/dev/null || true)"
fi

echo "[evidence] health_url=${health_url}"
if command -v curl >/dev/null 2>&1; then
  curl -sS --max-time 5 "${health_url}" || true
  echo
fi

echo "[evidence] docker_ps"
if command -v docker >/dev/null 2>&1; then
  docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.ID}}\t{{.Status}}' | (grep -i idc1-assistance || true)
  echo

  echo "[evidence] compose_ps"
  docker compose -f "${compose_file}" ps || true
  echo

  echo "[evidence] image_digests"
  for svc in jarvis-backend jarvis-frontend; do
    cid="$(docker compose -f "${compose_file}" ps -q "${svc}" 2>/dev/null || true)"
    if [[ -z "${cid}" ]]; then
      continue
    fi
    img="$(docker inspect --format '{{.Config.Image}}' "${cid}" 2>/dev/null || true)"
    dig="$(docker inspect --format '{{index .RepoDigests 0}}' "${cid}" 2>/dev/null || true)"
    echo "${svc} container=${cid} image=${img} digest=${dig}"
  done
  echo

  if [[ -n "${trace_id}" ]]; then
    echo "[evidence] backend_logs_filtered trace_id=${trace_id}"
    backend_cid="$(docker compose -f "${compose_file}" ps -q jarvis-backend 2>/dev/null || true)"
    if [[ -n "${backend_cid}" ]]; then
      docker logs --since 30m "${backend_cid}" 2>&1 | grep -F "${trace_id}" || true
    fi
    echo
  else
    echo "[evidence] backend_logs_tail"
    backend_cid="$(docker compose -f "${compose_file}" ps -q jarvis-backend 2>/dev/null || true)"
    if [[ -n "${backend_cid}" ]]; then
      docker logs --since 10m "${backend_cid}" 2>&1 | tail -n 200 || true
    fi
    echo
  fi
fi

echo "[evidence] done"
