#!/usr/bin/env bash
# Install the ada-* dependency health gate on tony-omen.
# kanban: ada-lane-health-gate-misses-notebooklm-dep (ADA-1369)
#
# Writes ~/.config/systemd/user/<unit>.service.d/dep-gate.conf for the
# lab lanes migrated idc03 -> tony-omen 2026-11-18 (SYS-0151). They
# arrived with NO drop-ins — neither the idc03 stagger nor any health
# gate followed the migration. The gate waits fail-closed until BOTH
# hard runtime deps answer their unauthenticated /health endpoints:
#   - MDDB leader       http://100.102.134.91:11023/health
#   - notebooklm-rest   http://100.123.163.11:3011/health  (idc02;
#     ConversationMemory->NotebooklmClient)
#
# No service restarts — the gate takes effect on each unit's next start.
# Idempotent — safe to rerun.
set -euo pipefail

# Lab lanes live here (verified active 2026-11-25); their env files carry
# NOTEBOOKLM_REST_BASE_URL. The disabled idc03 twins get the same gate
# from stacks/idc03/ada-dep-gate.
UNITS=(
  ada-dev
  ada-kk-dev
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
# No stagger.conf exists on tony-omen, so this drop-in's
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
