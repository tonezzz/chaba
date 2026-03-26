#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${JARVIS_BASE_URL:-http://127.0.0.1:18018}"
HEALTH_URL="${BASE_URL}/health"
STATUS_URL="${BASE_URL}/jarvis/api/debug/status"

PASS=0
FAIL=1

overall_result=$PASS

# Detect jq availability
if command -v jq &>/dev/null; then
  HAS_JQ=true
else
  HAS_JQ=false
  echo "[WARN] jq not found — falling back to grep-based checks."
fi

# ---------------------------------------------------------------------------
# Helper: curl a URL, return body in REPLY_BODY and HTTP status in REPLY_CODE
# ---------------------------------------------------------------------------
fetch() {
  local url="$1"
  local raw
  raw=$(curl -fsSL --max-time 10 -w "\nHTTP_STATUS:%{http_code}\n" "$url" 2>&1) || {
    echo "[ERROR] curl failed for ${url}" >&2
    REPLY_BODY=""
    REPLY_CODE="000"
    return 1
  }
  local status_line
  status_line=$(grep -Eo 'HTTP_STATUS:[0-9]+' <<<"$raw" || true)
  REPLY_BODY="${raw//$'\n'${status_line}/}"
  REPLY_BODY="${REPLY_BODY//$status_line/}"
  REPLY_CODE="${status_line#HTTP_STATUS:}"
}

# ---------------------------------------------------------------------------
# Check 1: /health
# ---------------------------------------------------------------------------
echo "[CHECK] Fetching ${HEALTH_URL} ..."

if fetch "$HEALTH_URL"; then
  echo "[INFO] HTTP ${REPLY_CODE}"
  echo "[INFO] Body: ${REPLY_BODY}"

  # Verify ok: true
  ok_found=false
  if $HAS_JQ; then
    ok_val=$(echo "$REPLY_BODY" | jq -r '.ok // empty' 2>/dev/null || true)
    [[ "$ok_val" == "true" ]] && ok_found=true
  else
    grep -q '"ok"\s*:\s*true' <<<"$REPLY_BODY" && ok_found=true || true
  fi

  if $ok_found; then
    echo "[PASS] /health reports ok: true"
  else
    echo "[FAIL] /health did not report ok: true" >&2
    overall_result=$FAIL
  fi

  # Print git_sha if present
  if $HAS_JQ; then
    git_sha=$(echo "$REPLY_BODY" | jq -r '.git_sha // empty' 2>/dev/null || true)
  else
    git_sha=$(grep -Eo '"git_sha"\s*:\s*"[^"]*"' <<<"$REPLY_BODY" | grep -Eo '"[^"]*"$' | tr -d '"' || true)
  fi
  if [[ -n "$git_sha" ]]; then
    echo "[INFO] git_sha: ${git_sha}"
  fi
else
  echo "[FAIL] Could not reach ${HEALTH_URL}" >&2
  overall_result=$FAIL
fi

echo

# ---------------------------------------------------------------------------
# Check 2: /jarvis/api/debug/status
# ---------------------------------------------------------------------------
echo "[CHECK] Fetching ${STATUS_URL} ..."

if fetch "$STATUS_URL"; then
  echo "[INFO] HTTP ${REPLY_CODE}"
  echo "[INFO] Body: ${REPLY_BODY}"

  # Verify ok: true
  ok_found=false
  if $HAS_JQ; then
    ok_val=$(echo "$REPLY_BODY" | jq -r '.ok // empty' 2>/dev/null || true)
    [[ "$ok_val" == "true" ]] && ok_found=true
  else
    grep -q '"ok"\s*:\s*true' <<<"$REPLY_BODY" && ok_found=true || true
  fi

  if $ok_found; then
    echo "[PASS] /jarvis/api/debug/status reports ok: true"
  else
    echo "[FAIL] /jarvis/api/debug/status did not report ok: true" >&2
    overall_result=$FAIL
  fi

  # Print failing dependency names if any
  if $HAS_JQ; then
    failing=$(echo "$REPLY_BODY" | jq -r '
      ( .dependencies // {} ) | to_entries[]
      | select(.value.ok == false or .value.healthy == false)
      | .key
    ' 2>/dev/null || true)
  else
    # Basic fallback: look for patterns like "name":{"ok":false} or "name":{"healthy":false}
    failing=$(grep -Eo '"[^"]+"\s*:\s*\{[^}]*(\"ok\"\s*:\s*false|\"healthy\"\s*:\s*false)[^}]*\}' <<<"$REPLY_BODY" \
      | grep -Eo '^"[^"]+"' | tr -d '"' || true)
  fi

  if [[ -n "$failing" ]]; then
    echo "[WARN] Failing dependencies:"
    while IFS= read -r dep; do
      echo "  - ${dep}"
    done <<<"$failing"
  fi
else
  echo "[FAIL] Could not reach ${STATUS_URL}" >&2
  overall_result=$FAIL
fi

echo

# ---------------------------------------------------------------------------
# Final result
# ---------------------------------------------------------------------------
if [[ $overall_result -eq $PASS ]]; then
  echo "[RESULT] PASS — jarvis-backend is healthy."
  exit 0
else
  echo "[RESULT] FAIL — one or more checks failed." >&2
  exit 1
fi
