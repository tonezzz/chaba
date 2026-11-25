#!/usr/bin/env bash
# Install the ada-* dependency health gate on mn01.
# kanban: ada-lane-health-gate-misses-notebooklm-dep (ADA-1369)
#
# Writes ~/.config/systemd/user/<unit>.service.d/dep-gate.conf for the
# disabled-but-running standby lanes (ada-ha-tony, ada-ha-michael — old
# naming; the idc03 kraut lane was renamed ada-ai-kraut). They carry
# NOTEBOOKLM_REST_BASE_URL and had no drop-ins at all. The gate waits
# fail-closed until BOTH hard runtime deps answer their unauthenticated
# /health endpoints:
#   - MDDB leader       http://100.102.134.91:11023/health
#   - notebooklm-rest   http://100.123.163.11:3011/health  (idc02;
#     ConversationMemory->NotebooklmClient)
#
# No service restarts — the gate takes effect on each unit's next start.
# Idempotent — safe to rerun.
set -euo pipefail

UNITS=(
  ada-ha-tony
  ada-ha-michael
)

[[ -d "$HOME/.config/systemd/user" ]] || mkdir -p "$HOME/.config/systemd/user"

for unit in "${UNITS[@]}"; do
  drop_dir="$HOME/.config/systemd/user/${unit}.service.d"
  mkdir -p "$drop_dir"
  cat > "$drop_dir/dep-gate.conf" <<'EOF'
# Dependency gate (kanban ada-lane-health-gate-misses-notebooklm-dep).
# ExecStartPre waits fail-closed until both hard runtime deps answer
# their unauthenticated /health endpoints: MDDB :11023 (memory bank) and
# notebooklm-rest :3011 on idc02 (ConversationMemory->NotebooklmClient).
# Warm-standby lane — no stagger.conf on mn01, so this drop-in's
# TimeoutStartSec=300 is the effective start budget.
[Unit]
After=mddb.service

[Service]
TimeoutStartSec=300
ExecStartPre=/bin/sh -c "for i in $(seq 1 90); do curl -sf --max-time 3 http://100.102.134.91:11023/health >/dev/null && curl -sf --max-time 3 http://100.123.163.11:3011/health >/dev/null && exit 0; sleep 5; done; exit 1"
EOF
done

systemctl --user daemon-reload
echo "dep-gate installed: ${#UNITS[@]} units (${UNITS[*]})"
