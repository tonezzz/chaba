#!/usr/bin/env bash
# verify-jarvis-frontend-status-panel.sh
#
# Confirms the deployed Jarvis frontend bundle includes the Debug Status Panel.
#
# Usage:
#   ./scripts/verify-jarvis-frontend-status-panel.sh
#
# Env overrides:
#   JARVIS_BASE_URL  – base URL of the Jarvis UI (default: http://127.0.0.1:18080/jarvis/)
#
# Exit code: 0 when all required strings are found, non-zero otherwise.

set -euo pipefail

JARVIS_BASE_URL="${JARVIS_BASE_URL:-http://127.0.0.1:18080/jarvis/}"

REQUIRED_STRINGS=(
  "jarvis_status_details_open"
  "/jarvis/api/debug/status"
  "Hide status details"
)

echo "[VERIFY] Fetching index page: ${JARVIS_BASE_URL}"
index_html=$(curl -fsSL "${JARVIS_BASE_URL}")

# Extract the first assets/*.js path from the HTML
js_path=$(echo "${index_html}" | grep -oE 'src="[^"]*assets/[^"]+\.js"' | head -n 1 | sed -E 's/^src="(.*)"$/\1/')

if [[ -z "${js_path}" ]]; then
  echo "[VERIFY] ERROR: Could not find an assets/*.js path in the index page." >&2
  exit 1
fi

# Normalise the base URL (strip trailing slash) then build the full bundle URL
base="${JARVIS_BASE_URL%/}"
if [[ "${js_path}" == http://* ]] || [[ "${js_path}" == https://* ]]; then
  js_url="${js_path}"
elif [[ "${js_path}" == /* ]]; then
  origin=$(echo "${base}" | sed -E 's#^(https?://[^/]+).*$#\1#')
  js_url="${origin}${js_path}"
else
  js_url="${base}/${js_path}"
fi

echo "[VERIFY] Resolved JS bundle URL: ${js_url}"
echo ""

tmpfile="$(mktemp)"
trap 'rm -f "${tmpfile}"' EXIT

curl -fsSL --compressed "${js_url}" -o "${tmpfile}"

# If the URL resolves to HTML instead of JS, this is usually an SPA fallback
# due to a reverse-proxy/nginx rewrite mismatch. Warn explicitly.
if head -n 2 "${tmpfile}" | grep -qiE '<!doctype html|<html'; then
  echo "[VERIFY] WARNING: Bundle URL returned HTML (SPA fallback) instead of JS." >&2
  echo "[VERIFY]          This usually means your base URL is not the same as the one used in the browser." >&2
  echo "[VERIFY]          Try running with the public URL, e.g.:" >&2
  echo "[VERIFY]            JARVIS_BASE_URL='https://<host>/jarvis/' ./scripts/verify-jarvis-frontend-status-panel.sh" >&2
fi

overall=0
for str in "${REQUIRED_STRINGS[@]}"; do
  if grep -qF "${str}" "${tmpfile}"; then
    echo "[VERIFY] PASS  \"${str}\""
  else
    echo "[VERIFY] FAIL  \"${str}\""
    overall=1
  fi
done

echo ""
if [[ "${overall}" -eq 0 ]]; then
  echo "[VERIFY] All checks passed. Debug Status Panel is present in the bundle."
else
  echo "[VERIFY] One or more checks FAILED. The bundle may be stale or incomplete." >&2
fi

exit "${overall}"
