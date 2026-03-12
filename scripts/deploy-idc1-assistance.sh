#!/usr/bin/env bash
set -euo pipefail

compose_file="stacks/idc1-assistance/docker-compose.yml"
repo="tonezzz/chaba"
workflow_name="Publish (idc1-assistance)"
branch="idc1-assistance"

# Controls
wait_timeout_seconds="${WAIT_TIMEOUT_SECONDS:-1800}"
poll_seconds="${POLL_SECONDS:-10}"
window_seconds="${HEALTH_WINDOW_SECONDS:-120}"

echo "[deploy] repo=${repo} workflow=${workflow_name} branch=${branch} compose=${compose_file}"

if ! command -v gh >/dev/null 2>&1; then
  echo "[deploy] ERROR: gh not found in PATH" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[deploy] ERROR: docker not found in PATH" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "[deploy] ERROR: gh not authenticated (run: gh auth login)" >&2
  exit 1
fi

echo "[deploy] Finding latest workflow run..."
run_id="$(gh run list --repo "${repo}" --workflow "${workflow_name}" --branch "${branch}" --limit 1 --json databaseId -q '.[0].databaseId')"
if [[ -z "${run_id}" || "${run_id}" == "null" ]]; then
  echo "[deploy] ERROR: no workflow runs found" >&2
  exit 1
fi

echo "[deploy] Latest run id: ${run_id}"

echo "[deploy] Waiting for workflow to complete (timeout=${wait_timeout_seconds}s)..."
start_ts="$(date +%s)"
while true; do
  status="$(gh run view "${run_id}" --repo "${repo}" --json status -q '.status')"
  conclusion="$(gh run view "${run_id}" --repo "${repo}" --json conclusion -q '.conclusion')"

  if [[ "${status}" == "completed" ]]; then
    if [[ "${conclusion}" == "success" ]]; then
      echo "[deploy] Workflow completed successfully."
      break
    fi
    echo "[deploy] ERROR: workflow completed but conclusion=${conclusion}" >&2
    echo "[deploy] Showing failed logs:" >&2
    gh run view "${run_id}" --repo "${repo}" --log-failed || true
    exit 1
  fi

  now_ts="$(date +%s)"
  elapsed="$((now_ts - start_ts))"
  if (( elapsed > wait_timeout_seconds )); then
    echo "[deploy] ERROR: timeout waiting for workflow (status=${status} conclusion=${conclusion})" >&2
    exit 1
  fi

  echo "[deploy] status=${status} conclusion=${conclusion} elapsed=${elapsed}s" 
  sleep "${poll_seconds}"
done

echo "[deploy] Collecting current running container image IDs..."
mapfile -t services < <(docker compose -f "${compose_file}" config --services)

if (( ${#services[@]} == 0 )); then
  echo "[deploy] ERROR: no services found in compose config" >&2
  exit 1
fi

declare -A running_image_by_service
for s in "${services[@]}"; do
  cid="$(docker compose -f "${compose_file}" ps -q "${s}" 2>/dev/null || true)"
  if [[ -z "${cid}" ]]; then
    running_image_by_service["${s}"]=""
    continue
  fi
  running_image_by_service["${s}"]="$(docker inspect -f '{{.Image}}' "${cid}" 2>/dev/null || true)"
done

echo "[deploy] Pulling stack images..."
docker compose -f "${compose_file}" pull

echo "[deploy] Determining which services changed..."
changed_services=()
for s in "${services[@]}"; do
  image_ref="$(docker compose -f "${compose_file}" config --images "${s}" 2>/dev/null | head -n 1 | tr -d '\r' || true)"
  if [[ -z "${image_ref}" ]]; then
    continue
  fi

  new_image_id="$(docker image inspect -f '{{.Id}}' "${image_ref}" 2>/dev/null || true)"
  old_image_id="${running_image_by_service["${s}"]}"

  if [[ -z "${new_image_id}" ]]; then
    echo "[deploy] WARN: could not inspect pulled image for service=${s} image=${image_ref}" >&2
    continue
  fi

  if [[ -z "${old_image_id}" ]]; then
    echo "[deploy] Service ${s}: not running -> will start/update (image=${image_ref})"
    changed_services+=("${s}")
    continue
  fi

  if [[ "${new_image_id}" != "${old_image_id}" ]]; then
    echo "[deploy] Service ${s}: CHANGED old=${old_image_id} new=${new_image_id} image=${image_ref}"
    changed_services+=("${s}")
  else
    echo "[deploy] Service ${s}: unchanged (image=${image_ref})"
  fi
done

if (( ${#changed_services[@]} == 0 )); then
  echo "[deploy] No services changed. Skipping redeploy to minimize downtime."
  exit 0
fi

echo "[deploy] Redeploying changed services only: ${changed_services[*]}"
# Recreate only changed services, but keep dependencies as-is.
docker compose -f "${compose_file}" up -d --no-deps --force-recreate "${changed_services[@]}"

echo "[deploy] Verifying container digests..."
for s in "${changed_services[@]}"; do
  cid="$(docker compose -f "${compose_file}" ps -q "${s}" 2>/dev/null || true)"
  if [[ -z "${cid}" ]]; then
    echo "[deploy] WARN: service ${s} has no container after deploy" >&2
    continue
  fi
  started="$(docker inspect -f '{{.State.StartedAt}}' "${cid}" 2>/dev/null || true)"
  image="$(docker inspect -f '{{.Config.Image}}' "${cid}" 2>/dev/null || true)"
  digest="$(docker inspect -f '{{.Image}}' "${cid}" 2>/dev/null || true)"
  echo "[deploy] ${s}: started=${started} image=${image} digest=${digest}"
done

echo "[deploy] Health check (best-effort)..."
# Jarvis backend is published to localhost:18018 by stack config. If it exists, check it.
if curl -fsS "http://127.0.0.1:18018/health" >/dev/null 2>&1; then
  echo "[deploy] jarvis-backend health OK"
else
  echo "[deploy] WARN: jarvis-backend health not OK yet; tailing logs (last ${window_seconds}s)" >&2
  docker logs --since "${window_seconds}s" --tail 400 idc1-assistance-jarvis-backend-1 2>/dev/null || true
fi

echo "[deploy] Done."
