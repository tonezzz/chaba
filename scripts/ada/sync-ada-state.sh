#!/usr/bin/env bash
# Sync per-host Ada runtime state from a source host to standby hosts:
#   ~/.local/share/ada-pi/speaker_profiles.json   (voiceprints + person bindings)
#   ~/.config/secrets/ada-ha-<inst>-keys.json     (issued device keys)
#
# Usage: sync-ada-state.sh <src-host> <dst-host> [<dst-host>...]
#   e.g. sync-ada-state.sh idc01 mn01
set -euo pipefail

src="${1:-}"; shift || true
if [[ -z "$src" || $# -lt 1 ]]; then
  echo "usage: $0 <src-host> <dst-host> [<dst-host>...]" >&2
  exit 2
fi

FILES=(
  ".local/share/ada-pi/speaker_profiles.json"
  ".config/secrets/ada-ha-tony-keys.json"
  ".config/secrets/ada-ha-michael-keys.json"
)

for dst in "$@"; do
  echo "== $src -> $dst"
  for f in "${FILES[@]}"; do
    if ssh "$src" "test -f ~/$f" 2>/dev/null; then
      ssh "$dst" "mkdir -p ~/$(dirname "$f")"
      ssh "$src" "cat ~/$f" | ssh "$dst" "cat > ~/$f.tmp && mv ~/$f.tmp ~/$f"
      echo "  synced $f"
    else
      echo "  skipped $f (absent on $src)"
    fi
  done
done
