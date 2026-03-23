#!/usr/bin/env bash
set -euo pipefail

# Default to the dev stack because prod is Git-backed and may require manual UI changes.
# Override via COMPOSE_FILE/PORTAINER_STACK_NAME/HEALTHCHECK_URL when needed.
compose_file="${COMPOSE_FILE:-stacks/idc1-assistance-dev/docker-compose.yml}"
repo="tonezzz/chaba"
workflow_name="Publish (idc1-assistance)"
branch="idc1-assistance"

# Portainer-first deploy trigger (Community Edition compatible)
# Set these on the Docker host (do not commit secrets):
#   export PORTAINER_URL='https://<portainer-host>'
#   export PORTAINER_API_KEY='ptr_...'
# Optional:
#   export PORTAINER_ENDPOINT_ID='2'
#   export PORTAINER_STACK_NAME='idc1-assistance'
portainer_url="${PORTAINER_URL:-}"
portainer_api_key="${PORTAINER_API_KEY:-}"
portainer_endpoint_id="${PORTAINER_ENDPOINT_ID:-2}"
portainer_stack_name="${PORTAINER_STACK_NAME:-idc1-assistance-dev}"
portainer_container_name="${PORTAINER_CONTAINER_NAME:-idc1-portainer}"

healthcheck_url="${HEALTHCHECK_URL:-http://127.0.0.1:28018/health}"
healthcheck_container_name="${HEALTHCHECK_CONTAINER_NAME:-${portainer_stack_name}-jarvis-backend-1}"

# Convenience: allow using the same token used by the local Portainer MCP stack.
# - `PORTAINER_TOKEN` is treated as an alias of `PORTAINER_API_KEY`.
# - If neither is set, we will attempt to source `stacks/idc1-portainer/.env` (local-only).
if [[ -z "${portainer_api_key}" && -n "${PORTAINER_TOKEN:-}" ]]; then
  portainer_api_key="${PORTAINER_TOKEN}"
fi

if [[ -z "${portainer_api_key}" && -f "stacks/idc1-portainer/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "stacks/idc1-portainer/.env"
  set +a
  if [[ -z "${portainer_api_key}" && -n "${PORTAINER_TOKEN:-}" ]]; then
    portainer_api_key="${PORTAINER_TOKEN}"
  fi
fi

# Controls
wait_timeout_seconds="${WAIT_TIMEOUT_SECONDS:-1800}"
poll_seconds="${POLL_SECONDS:-10}"
window_seconds="${HEALTH_WINDOW_SECONDS:-120}"
force_redeploy="${FORCE_REDEPLOY:-0}"

echo "[deploy] repo=${repo} workflow=${workflow_name} branch=${branch} compose=${compose_file}"

# Ensure sub-processes (python snippets) see the same compose file.
export COMPOSE_FILE="${compose_file}"

get_container_id() {
  local service="$1"
  local cid=""

  # Prefer docker compose (when containers have compose labels)
  cid="$(docker compose -f "${compose_file}" ps -q "${service}" 2>/dev/null || true)"
  if [[ -n "${cid}" ]]; then
    echo "${cid}"
    return 0
  fi

  # Fallback: explicit container name convention used by this stack
  cid="$(docker ps --filter "name=^/${portainer_stack_name}-${service}-1$" --format '{{.ID}}' | head -n 1)"
  if [[ -n "${cid}" ]]; then
    echo "${cid}"
    return 0
  fi

  return 1
}

trigger_portainer_redeploy() {
  if [[ -z "${portainer_api_key}" ]]; then
    echo "[deploy] ERROR: PORTAINER_API_KEY is not set" >&2
    return 1
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "[deploy] ERROR: curl not found in PATH" >&2
    return 1
  fi

  # Portainer CE commonly exposes HTTP on :9000 (local) and HTTPS on :9443.
  # Many setups only have :9000 listening locally.
  if [[ -z "${portainer_url}" ]]; then
    portainer_url="http://127.0.0.1:9000"
  fi
  base="${portainer_url%/}"

  echo "[deploy] Checking Portainer API connectivity: ${base}/api/status"
  http_code="$(curl -sS -k --max-time 5 -o /tmp/portainer_status.json -w '%{http_code}' "${base}/api/status" || true)"
  if [[ "${http_code}" != "200" ]]; then
    echo "[deploy] ERROR: cannot reach Portainer API at ${base} (http=${http_code})." >&2
    echo "[deploy] Hint: On this host Portainer often listens on http://127.0.0.1:9000 (not :9443)." >&2
    head -c 600 /tmp/portainer_status.json 2>/dev/null || true
    echo >&2
    return 1
  fi

  echo "[deploy] Discovering stack id for name=${portainer_stack_name} endpointId=${portainer_endpoint_id}"
  stacks_http="$(curl -sS -k --max-time 30 -o /tmp/portainer_stacks.json -w '%{http_code}' -H "X-API-Key: ${portainer_api_key}" "${base}/api/stacks" || true)"
  if [[ "${stacks_http}" != "200" ]]; then
    echo "[deploy] ERROR: Portainer /api/stacks returned http=${stacks_http}" >&2
    head -c 800 /tmp/portainer_stacks.json 2>/dev/null || true
    echo >&2
    return 1
  fi

  stack_id="$(STACK_NAME="${portainer_stack_name}" ENDPOINT_ID="${portainer_endpoint_id}" python3 - <<'PY'
import json,os,sys

name=os.environ.get('STACK_NAME','')
endpoint_id=os.environ.get('ENDPOINT_ID','')
try:
    endpoint_id_int=int(endpoint_id)
except Exception:
    endpoint_id_int=None

try:
    with open('/tmp/portainer_stacks.json','r',encoding='utf-8') as f:
        obj=json.load(f)
except Exception as e:
    print(f"PARSE_ERROR {e}", file=sys.stderr)
    raise

sid=None
if isinstance(obj, list):
    for s in obj:
        if not isinstance(s, dict):
            continue
        if str(s.get('Name') or '') != name:
            continue
        if endpoint_id_int is not None and int(s.get('EndpointId') or -1) != endpoint_id_int:
            continue
        sid=s.get('Id')
        break

print(sid or '')
PY
)"

  if [[ -z "${stack_id}" ]]; then
    echo "[deploy] ERROR: could not find stack id for name=${portainer_stack_name}" >&2
    return 1
  fi

  echo "[deploy] stack_id=${stack_id}"

  echo "[deploy] Fetching current stack file and env from Portainer"
  curl -sS -k --max-time 30 -H "X-API-Key: ${portainer_api_key}" "${base}/api/stacks/${stack_id}/file" -o /tmp/portainer_stack_file.json
  curl -sS -k --max-time 30 -H "X-API-Key: ${portainer_api_key}" "${base}/api/stacks/${stack_id}" -o /tmp/portainer_stack_inspect.json

  # IMPORTANT:
  # Updating a Git-backed stack via PUT /api/stacks/{id} will convert it to a file-based stack.
  # If you want to keep the stack Git-backed, use the Git redeploy endpoint.
  is_git_stack="$(python3 - <<'PY'
import json
with open('/tmp/portainer_stack_inspect.json','r',encoding='utf-8') as f:
  obj=json.load(f)
git_cfg=obj.get('GitConfig')
is_git=bool(git_cfg) and isinstance(git_cfg, dict)
print('1' if is_git else '0')
PY
  )"
  if [[ "${is_git_stack}" == "1" ]]; then
    echo "[deploy] Git-backed stack detected. Redeploying via Portainer Git redeploy endpoint." >&2

    # Portainer expects a JSON body for git redeploy (at least pullImage).
    # If the body is empty, Portainer may not refresh the git checkout, which can lead to
    # missing compose files under /data/compose/<id>/...
    git_payload='{"pullImage":true,"prune":true}'

    # Portainer CE supports Git-backed stacks. The UI uses a Git redeploy endpoint.
    # Different Portainer versions differ in the expected method (POST vs PUT).
    # Some versions may return a non-2xx on POST but still accept PUT.
    git_http_code="$(curl -sS -k --max-time 120 -o /tmp/portainer_git_redeploy.json -w '%{http_code}' \
      -X POST \
      -H "X-API-Key: ${portainer_api_key}" \
      -H 'Content-Type: application/json' \
      --data-binary "${git_payload}" \
      "${base}/api/stacks/${stack_id}/git/redeploy?endpointId=${portainer_endpoint_id}" || true)"

    if [[ "${git_http_code}" != "200" && "${git_http_code}" != "204" ]]; then
      git_http_code="$(curl -sS -k --max-time 120 -o /tmp/portainer_git_redeploy.json -w '%{http_code}' \
        -X PUT \
        -H "X-API-Key: ${portainer_api_key}" \
        -H 'Content-Type: application/json' \
        --data-binary "${git_payload}" \
        "${base}/api/stacks/${stack_id}/git/redeploy?endpointId=${portainer_endpoint_id}" || true)"
    fi

    if [[ "${git_http_code}" == "200" || "${git_http_code}" == "204" ]]; then
      echo "[deploy] Portainer Git redeploy OK (http=${git_http_code})" >&2
      return 0
    fi

    if [[ "${git_http_code}" == "404" ]]; then
      echo "[deploy] ERROR: Portainer Git redeploy endpoint not found (http=404)." >&2
    else
      echo "[deploy] ERROR: Portainer Git redeploy failed (http=${git_http_code})." >&2
    fi
    head -c 1500 /tmp/portainer_git_redeploy.json 2>/dev/null || true
    echo >&2

    if [[ "${ALLOW_GIT_DETACH_FALLBACK:-0}" == "1" || "${ALLOW_GIT_DETACH_FALLBACK:-0}" == "true" || "${ALLOW_GIT_DETACH_FALLBACK:-0}" == "yes" ]]; then
      if [[ ! -f "${compose_file}" ]]; then
        echo "[deploy] ERROR: compose_file not found on disk: ${compose_file}" >&2
        return 1
      fi

      echo "[deploy] Falling back to file-based stack update (this will detach the stack from Git)." >&2

      # Portainer will attempt to persist the stack file to /data/compose/<id>/<EntryPoint>.
      # When Git checkout is broken, that path may not exist. Ensure it exists in the Portainer /data volume.
      entrypoint_path="$(python3 - <<'PY'
import json
with open('/tmp/portainer_stack_inspect.json','r',encoding='utf-8') as f:
  obj=json.load(f)
print((obj.get('EntryPoint') or '').strip())
PY
      )"
      if [[ -z "${entrypoint_path}" ]]; then
        echo "[deploy] ERROR: missing stack EntryPoint from Portainer inspect" >&2
        return 1
      fi

      if ! command -v docker >/dev/null 2>&1; then
        echo "[deploy] ERROR: docker not found in PATH" >&2
        return 1
      fi

      if ! docker ps --format '{{.Names}}' | grep -qx "${portainer_container_name}"; then
        echo "[deploy] ERROR: Portainer container not found: ${portainer_container_name}" >&2
        echo "[deploy] Hint: set PORTAINER_CONTAINER_NAME if your Portainer container name differs." >&2
        return 1
      fi

      echo "[deploy] Ensuring Portainer stack entrypoint exists: /data/compose/${stack_id}/${entrypoint_path}" >&2
      entrypoint_dir="$(python3 - <<'PY'
import os
import sys
ep=sys.argv[1] if len(sys.argv) > 1 else ''
print(os.path.dirname(ep) if ep else '')
PY
        "${entrypoint_path}"
      )"
      docker run --rm \
        --volumes-from "${portainer_container_name}" \
        -v "$(readlink -f "${compose_file}"):/tmp/stack-compose.yml:ro" \
        alpine:3.20 \
        sh -lc 'set -e; mkdir -p "/data/compose/${STACK_ID}/${ENTRYPOINT_DIR}"; cp /tmp/stack-compose.yml "/data/compose/${STACK_ID}/${ENTRYPOINT_PATH}"' \
        -e "STACK_ID=${stack_id}" \
        -e "ENTRYPOINT_PATH=${entrypoint_path}" \
        -e "ENTRYPOINT_DIR=${entrypoint_dir}"

      python3 - <<'PY'
import json
import os

compose_file=os.environ.get('COMPOSE_FILE')
if not compose_file:
    raise SystemExit('COMPOSE_FILE not set')

with open('/tmp/portainer_stack_inspect.json','r',encoding='utf-8') as f:
    inspect_obj=json.load(f)

with open(compose_file,'r',encoding='utf-8') as f:
    stack_file=f.read()

env_list=inspect_obj.get('Env') or []

out={
  'StackFileContent': stack_file,
  'Env': env_list,
  'Prune': True,
  'RepullImageAndRedeploy': True,
}

with open('/tmp/portainer_stack_update_payload.json','w',encoding='utf-8') as f:
    json.dump(out,f)
PY

      http_code="$(curl -sS -k --max-time 120 -o /tmp/portainer_stack_update.json -w '%{http_code}' \
        -X PUT \
        -H "X-API-Key: ${portainer_api_key}" \
        -H 'Content-Type: application/json' \
        "${base}/api/stacks/${stack_id}?endpointId=${portainer_endpoint_id}" \
        --data-binary @/tmp/portainer_stack_update_payload.json)"

      if [[ "${http_code}" != "200" ]]; then
        echo "[deploy] ERROR: Portainer stack update returned http=${http_code}" >&2
        head -c 1500 /tmp/portainer_stack_update.json 2>/dev/null || true
        echo
        return 1
      fi

      echo "[deploy] Portainer stack update OK (http=${http_code})" >&2
      return 0
    fi

    echo "[deploy] Action: redeploy via Portainer UI (Pull and redeploy)." >&2
    echo "[deploy] Note: set ALLOW_GIT_DETACH_FALLBACK=1 to allow this script to detach and redeploy as a file-based stack." >&2
    return 1
  fi

  # Prepare update payload:
  # - StackFileContent from /file
  # - Env from stack inspect
  # - RepullImageAndRedeploy=true to force redeploy with fresh images
  python3 - <<'PY'
import json

with open('/tmp/portainer_stack_file.json','r',encoding='utf-8') as f:
  file_obj=json.load(f)
with open('/tmp/portainer_stack_inspect.json','r',encoding='utf-8') as f:
  inspect_obj=json.load(f)

stack_file=file_obj.get('StackFileContent') or ''
env_list=inspect_obj.get('Env') or []

out={
  'StackFileContent': stack_file,
  'Env': env_list,
  'Prune': True,
  'RepullImageAndRedeploy': True,
}

with open('/tmp/portainer_stack_update_payload.json','w',encoding='utf-8') as f:
  json.dump(out,f)
PY

  if [[ ! -s "/tmp/portainer_stack_update_payload.json" ]]; then
    echo "[deploy] ERROR: failed to build update payload" >&2
    return 1
  fi

  echo "[deploy] Redeploying stack via Portainer API (PUT /api/stacks/{id})"
  http_code="$(curl -sS -k --max-time 120 -o /tmp/portainer_stack_update.json -w '%{http_code}' \
    -X PUT \
    -H "X-API-Key: ${portainer_api_key}" \
    -H 'Content-Type: application/json' \
    "${base}/api/stacks/${stack_id}?endpointId=${portainer_endpoint_id}" \
    --data-binary @/tmp/portainer_stack_update_payload.json)"

  if [[ "${http_code}" != "200" ]]; then
    echo "[deploy] ERROR: Portainer stack update returned http=${http_code}" >&2
    head -c 1500 /tmp/portainer_stack_update.json 2>/dev/null || true
    echo
    return 1
  fi

  echo "[deploy] Portainer stack update OK (http=${http_code})"
  return 0
}

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
  cid="$(get_container_id "${s}" || true)"
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
declare -A image_by_service
while IFS=$'\t' read -r svc_name img_ref; do
  if [[ -n "${svc_name}" && -n "${img_ref}" ]]; then
    image_by_service["${svc_name}"]="${img_ref}"
  fi
done < <(python3 - <<'PY'
import json
import subprocess
import os

compose_file = os.environ.get("COMPOSE_FILE") or "stacks/idc1-assistance-dev/docker-compose.yml"
cp = subprocess.run(
    ["docker", "compose", "-f", compose_file, "config", "--format", "json"],
    check=True,
    capture_output=True,
    text=True,
)
obj = json.loads(cp.stdout)
services = obj.get("services") or {}
for name, svc in services.items():
    img = (svc or {}).get("image") or ""
    if img:
        print(f"{name}\t{img}")
PY
)

for s in "${services[@]}"; do
  image_ref="${image_by_service["${s}"]:-}"
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

if [[ "${force_redeploy}" == "1" || "${force_redeploy}" == "true" || "${force_redeploy}" == "yes" ]]; then
  echo "[deploy] FORCE_REDEPLOY is set. Forcing Portainer redeploy even if image digests are unchanged."
  changed_services=("${services[@]}")
fi

if (( ${#changed_services[@]} == 0 )); then
  echo "[deploy] No services changed. Skipping redeploy to minimize downtime."
  exit 0
fi

echo "[deploy] Changes detected. Triggering Portainer-authoritative redeploy."
if ! trigger_portainer_redeploy; then
  exit 1
fi

echo "[deploy] Verifying container digests..."
for s in "${changed_services[@]}"; do
  cid="$(get_container_id "${s}" || true)"
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
# If it exists, check it.
if curl -fsS "${healthcheck_url}" >/dev/null 2>&1; then
  echo "[deploy] jarvis-backend health OK"
else
  echo "[deploy] WARN: jarvis-backend health not OK yet; tailing logs (last ${window_seconds}s)" >&2
  docker logs --since "${window_seconds}s" --tail 400 "${healthcheck_container_name}" 2>/dev/null || true
fi

echo "[deploy] Done."
