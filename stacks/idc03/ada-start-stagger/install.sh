#!/usr/bin/env bash
# Install the ada-* fleet-start stagger on idc03.
# kanban: idc03-stagger-ada-fleet-restarts-mass-re-ae9de7
#
# Writes ~/.local/bin/ada-start-stagger.sh plus one
# ~/.config/systemd/user/<unit>.d/stagger.conf per ada backend, then
# daemon-reload. Idempotent — safe to rerun after offset changes.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Stagger offsets (seconds) — order is the documented canary ladder from
# deploy-ada.sh: tony's lane first, then small/edge lanes, member lanes,
# lab twins last. ~700MB pwa_server ramps serialize one at a time.
declare -A OFFSETS=(
  [ada-ha-tony]=0
  [ada-bankq-student]=10
  [ada-chaba]=20
  [ada-ai-kraut]=35
  [ada-kk]=65
  [ada-kk-dev]=80
  [ada-dev]=95
  [ada-ha-ada]=110
)

install -m 0755 "$SCRIPT_DIR/ada-start-stagger.sh" "$HOME/.local/bin/ada-start-stagger.sh"

for unit in "${!OFFSETS[@]}"; do
  drop_dir="$HOME/.config/systemd/user/${unit}.service.d"
  [[ -d "$HOME/.config/systemd/user" ]] || mkdir -p "$HOME/.config/systemd/user"
  mkdir -p "$drop_dir"
  cat > "$drop_dir/stagger.conf" <<EOF
# Fleet-restart stagger (kanban idc03-stagger-ada-fleet-restarts-mass-re-ae9de7).
# Serializes simultaneous ada backend starts so the ~700MB pwa_server
# ramps happen one at a time (2026-11-16 load-11.8 incident). A lone
# start (crash recovery, single \`systemctl restart\`) skips the sleep.
[Service]
TimeoutStartSec=180
ExecStartPre=%h/.local/bin/ada-start-stagger.sh ${OFFSETS[$unit]}
EOF
done

systemctl --user daemon-reload
echo "stagger installed: ${#OFFSETS[@]} units (offsets: $(for u in "${!OFFSETS[@]}"; do printf '%s=%s ' "$u" "${OFFSETS[$u]}"; done))"
