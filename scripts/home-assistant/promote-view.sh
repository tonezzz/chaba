#!/usr/bin/env bash
# One-shot promotion pipeline:
#   apply-tpl.py (dev, optional) -> copy-view.py (dev -> michael-ha) -> sync-ssot -> commit
#
# Usage:
#   promote-view.sh <view> [options]
#     --map "Title:r,c;..."   apply TPL templates onto the dev view first
#     --first | --after <p>   placement on michael-ha (default: keep dev's position index)
#     --dash <path>           dashboard url_path (default tony-test)
#     --no-commit             skip the git commit step
#
# Example:
#   promote-view.sh pfg2 --map "Grid:1,7;Battery:5,1" --first
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
DEV_URL="https://tony-dell.taila0626a.ts.net:8124"
HA_URL="http://michael-ha:8123"
DASH="tony-test"
VIEW="${1:?usage: promote-view.sh <view> [--map ...] [--first|--after <path>] [--no-commit]}"
shift

MAP=""; PLACE=(); COMMIT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --map) MAP="$2"; shift 2 ;;
    --first) PLACE=(--first); shift ;;
    --after) PLACE=(--after "$2"); shift 2 ;;
    --dash) DASH="$2"; shift 2 ;;
    --no-commit) COMMIT=0; shift ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

set -a; source ~/.config/secrets/ha-michael-dev.env; set +a
export SRC_TOKEN="$HASS_TOKEN"
export DST_TOKEN="$(cat ~/.local/share/home-assistant-michael/ha-token)"

if [ -n "$MAP" ]; then
  echo "== apply-tpl on dev =="
  python3 "$REPO/scripts/home-assistant/apply-tpl.py" "$DEV_URL" "$DASH" tpl "$VIEW" --map "$MAP"
fi

echo "== copy view dev -> michael-ha =="
python3 "$REPO/scripts/home-assistant/copy-view.py" "$DEV_URL" "$HA_URL" "$VIEW" --dash "$DASH" "${PLACE[@]}"

echo "== sync ssot =="
bash "$REPO/scripts/home-assistant/sync-ssot-from-live.sh"

node "$REPO/scripts/ssot-validate-all.mjs" >/dev/null && echo "ssot: valid"

if [ "$COMMIT" = 1 ]; then
  git -C "$REPO" add -A
  git -C "$REPO" commit -m "promote-view: $VIEW${MAP:+ (map: $MAP)}

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>" || echo "nothing to commit"
fi
