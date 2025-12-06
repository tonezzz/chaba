#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${TARGET_URL:-https://a1.idc1.surf-thailand.com/test}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-5}"
SLEEP_SECONDS="${SLEEP_SECONDS:-5}"

echo "[VERIFY] Checking ${TARGET_URL}"

attempt=1
while (( attempt <= MAX_ATTEMPTS )); do
  echo "[VERIFY] Attempt ${attempt}/${MAX_ATTEMPTS}"
  if response=$(curl -fsSL -w "\nHTTP_STATUS:%{http_code}\n" "$TARGET_URL"); then
    status_line=$(grep -Eo 'HTTP_STATUS:[0-9]+' <<<"$response" || true)
    body="${response//$status_line/}"
    status_code="${status_line#HTTP_STATUS:}"
    echo "[VERIFY] Status code: ${status_code}"
    if [[ -n "$body" ]]; then
      echo "[VERIFY] Body preview:"
      echo "$body" | head -n 20
    fi
    exit 0
  fi

  echo "[VERIFY] Failed attempt ${attempt}. Retrying in ${SLEEP_SECONDS}s..."
  sleep "$SLEEP_SECONDS"
  ((attempt++))
done

echo "[VERIFY] Endpoint did not respond successfully after ${MAX_ATTEMPTS} attempts."
exit 1
