#!/usr/bin/env bash
# Fail CI if operational files still reference the legacy tony-omen:8080 endpoints.
# Caddy/apps now live on tony-dell:8080; yomi-api lives on tony-dell:3000.
set -euo pipefail

fail=0
patterns=(
  'http://tony-omen:8080'
  'http://tony-omen.local:8080'
  'ws://tony-omen:8080'
  'ws://tony-omen.local:8080'
)

# Directories/files to scan (docs and generated public/ copies are excluded)
check_args=(
  scripts
  mcp-servers
  stacks/web/public/apps/index.html
  stacks/web/public/apps/tailscale-funnel/index.html
  stacks/web/public/apps/trade/tradecanvas-ui/app.js
)

for pat in "${patterns[@]}"; do
  matches=$(grep -RIn \
    --include='*.mjs' --include='*.sh' --include='*.py' \
    --include='*.js' --include='*.html' \
    "$pat" "${check_args[@]}" 2>/dev/null | grep -v '/ssot-check-stale-urls.sh' || true)
  if [[ -n "$matches" ]]; then
    echo "ERROR: stale URL pattern '$pat' found in operational files:" >&2
    echo "$matches" >&2
    fail=1
  fi
done

if [[ $fail -ne 0 ]]; then
  echo "Remove or correct the stale tony-omen:8080 URLs before merging." >&2
  exit 1
fi

echo "OK: no stale tony-omen:8080 URLs in operational files."
