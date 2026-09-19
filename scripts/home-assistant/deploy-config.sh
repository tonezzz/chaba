#!/usr/bin/env bash
# Deploy HA config to dev and/or live with one command.
#
# Usage:
#   deploy-config.sh --host dev|ha|all [--check]
#
#   --host dev   rsync repo config -> michael-dev (tony-dell) + reload
#   --host ha    rsync repo config -> michael-ha + reload
#   --host all   both, dev first
#   --check      dry-run: diff repo config vs each target without deploying
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." &>/dev/null && pwd)
HA_DIR="$REPO_ROOT/docs/home-assistant/configuration"

HOST=""
CHECK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --check|--dry-run) CHECK=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$HOST" ] || { echo "usage: deploy-config.sh --host dev|ha|all [--check]"; exit 2; }

DEV_CONFIG_SSH='tony-dell:/home/tony/.config/michael-dev/'
HA_CONFIG_SSH='michael-ha:/config/'
# dev is reached over ssh because this script may run from any host

if [ "$CHECK" -eq 1 ]; then
  echo "[deploy-config] dry-run diff (repo -> target)"
  case "$HOST" in
    dev|all)
      echo "--- dev ---"
      rsync -avzn --delete --exclude='.storage*' --exclude='*.db*' \
        --exclude='home-assistant.log*' --exclude='tts/' --exclude='deps/' \
        -e ssh "$HA_DIR/" "$DEV_CONFIG_SSH" | tail -40 ;;
  esac
  case "$HOST" in
    ha|all)
      echo "--- michael-ha ---"
      rsync -avzn -e "ssh -i ${MICHAEL_SSH_KEY:-$HOME/.ssh/michael-ha}" \
        --exclude='.storage*' --exclude='*.db*' --exclude='home-assistant.log*' \
        --exclude='tts/' --exclude='deps/' --exclude='image/' \
        "$HA_DIR/" "$HA_CONFIG_SSH" | tail -40 ;;
  esac
  exit 0
fi

case "$HOST" in
  dev) "$SCRIPT_DIR/deploy-michael-dev.sh" ;;
  ha)  "$SCRIPT_DIR/deploy-michael.sh" ;;
  all) "$SCRIPT_DIR/deploy-michael-dev.sh" && "$SCRIPT_DIR/deploy-michael.sh" ;;
  *) echo "unknown host: $HOST"; exit 2 ;;
esac
