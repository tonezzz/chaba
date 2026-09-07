#!/usr/bin/env bash
# Build + deploy the forked sunsynk-power-flow-card.
# Usage: deploy-card.sh [--host michael-dev|michael-ha]   (default michael-dev)
#        deploy-card.sh --host all                        (both hosts)
# Version is derived from the remote lovelace_resources (single source of truth)
# so parallel sessions cannot collide on "next version".
set -euo pipefail

# Deploy lock: only one session may build/deploy at a time (parallel sessions
# collided on versions and pushed half-written code — see AGENTS.md worktree rules).
LOCK=/tmp/pfg-deploy.lock
exec 9>"$LOCK"
flock -n 9 || { echo "ERROR: another deploy is in progress ($LOCK)"; exit 1; }

CARD_REPO="${CARD_REPO:-/home/tony/CascadeProjects/sunsynk-power-flow-card}"
BASE="sunsynk-power-flow-card-fork"

TARGET="michael-dev"
[ "${1:-}" = "--host" ] && TARGET="$2"

# --check: compare local dist md5 vs each host's ACTIVE bundle (no build/deploy)
if [ "${1:-}" = "--check" ]; then
  LOCAL_MD5=$(md5sum "$CARD_REPO/dist/sunsynk-power-flow-card.js" | cut -d' ' -f1)
  for host in michael-dev michael-ha; do
    case "$host" in
      michael-dev) SSH=tony-dell; RES=/home/tony/.config/michael-dev/.storage/lovelace_resources; WWW=/home/tony/.config/michael-dev/www ;;
      michael-ha)  SSH=michael-ha; RES=/config/.storage/lovelace_resources; WWW=/config/www ;;
    esac
    FILE=$(ssh "$SSH" "grep -o '${BASE}-v[0-9]*\.js' '$RES' | head -1" || true)
    [ -n "$FILE" ] || { echo "$host: no active $BASE resource"; continue; }
    REMOTE_MD5=$(ssh "$SSH" "md5sum '$WWW/$FILE'" | cut -d' ' -f1)
    if [ "$REMOTE_MD5" = "$LOCAL_MD5" ]; then echo "$host: $FILE MATCHES dist"; else echo "$host: $FILE DRIFT (remote=$REMOTE_MD5 local=$LOCAL_MD5)"; fi
  done
  exit 0
fi

deploy_to() {
  local host="$1" SSH WWW RES RESTART URL_BASE
  case "$host" in
    michael-dev)
      SSH=tony-dell; WWW=/home/tony/.config/michael-dev/www
      RES=/home/tony/.config/michael-dev/.storage/lovelace_resources
      RESTART="systemctl --user restart michael-dev.service"
      URL_BASE="https://tony-dell.taila0626a.ts.net:8124" ;;
    michael-ha)
      SSH=michael-ha; WWW=/config/www
      RES=/config/.storage/lovelace_resources
      RESTART="ha core restart"
      URL_BASE="http://michael-ha:8123" ;;
    *) echo "unknown host $host" >&2; return 1 ;;
  esac

  local cur next file code i
  cur=$(ssh "$SSH" "grep -o '${BASE}-v[0-9]*' '$RES' | head -1 | grep -o '[0-9]*$'")
  [ -n "$cur" ] || { echo "ERROR: no existing ${BASE}-vN resource on $host:$RES"; return 1; }
  next=$((cur + 1))
  file="${BASE}-v${next}.js"
  echo "[$host] current: v$cur -> deploying v$next"

  scp "dist/sunsynk-power-flow-card.js" "$SSH:$WWW/$file"
  ssh "$SSH" "sed -i 's|${BASE}-v[0-9]*\.js|${file}|g' '$RES' && $RESTART"

  echo -n "[$host] waiting for HA..."
  code=""
  for i in $(seq 1 60); do
    code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$URL_BASE/local/$file" || true)
    [ "$code" = "200" ] && break
    sleep 3
  done
  echo " ${code:-timeout}"
  [ "$code" = "200" ] || { echo "ERROR: bundle not served on $host"; return 1; }
  local local_md5 remote_md5
  local_md5=$(md5sum dist/sunsynk-power-flow-card.js | cut -d' ' -f1)
  remote_md5=$(ssh "$SSH" "md5sum '$WWW/$file'" | cut -d' ' -f1)
  [ "$remote_md5" = "$local_md5" ] && echo "[$host] md5 verified ($local_md5)" || echo "[$host] WARNING: md5 mismatch ($remote_md5 vs $local_md5)"
  echo "[$host] deployed /local/$file"
}

cd "$CARD_REPO"
npm run build

if [ "$TARGET" = "all" ]; then
  deploy_to michael-dev
  deploy_to michael-ha
else
  deploy_to "$TARGET"
fi
