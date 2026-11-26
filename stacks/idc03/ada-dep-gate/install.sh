#!/usr/bin/env bash
# Install the ada-* dependency health gate on idc03.
# kanban: ada-lane-health-gate-misses-notebooklm-dep (ADA-1369)
#
# Writes ~/.config/systemd/user/<unit>.service.d/dep-gate.conf for every
# ada lane whose env carries NOTEBOOKLM_REST_BASE_URL, and removes the
# superseded ad-hoc mddb-gate.conf (MDDB-only, created 2026-10-05,
# untracked in any repo). The gate waits fail-closed until BOTH hard
# runtime deps answer their unauthenticated /health endpoints:
#   - MDDB leader       http://100.102.134.91:11023/health
#   - notebooklm-rest   http://100.123.163.11:3011/health  (idc02;
#     ConversationMemory->NotebooklmClient — dead ~5 weeks before the
#     2026-11-25 repoint because no gate covered it)
#
# No service restarts — the gate takes effect on each unit's next start.
# Idempotent — safe to rerun.
set -euo pipefail

# Lanes gated on both deps. ada-bankq-student is excluded — its env has
# no NOTEBOOKLM_REST_BASE_URL (open-jev student lane, not a voice lane).
# ada-dev/ada-kk-dev are disabled on idc03 (lab twins live on tony-omen)
# but keep the drop-in for parity with stagger.conf — if started here
# they still gate.
UNITS=(
  ada-ha-tony
  ada-chaba
  ada-ai-kraut
  ada-kk
  ada-kk-dev
  ada-dev
  ada-ha-ada
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
# Supersedes the ad-hoc mddb-gate.conf (2026-10-05, MDDB-only).
# Note: on idc03 lanes stagger.conf is a lexically-later drop-in and its
# TimeoutStartSec=180 wins over the 300 below — same effective budget the
# old mddb-gate already ran under.
[Unit]
After=mddb.service

[Service]
TimeoutStartSec=300
ExecStartPre=/bin/sh -c "for i in $(seq 1 90); do curl -sf --max-time 3 http://100.102.134.91:11023/health >/dev/null && curl -sf --max-time 3 http://100.123.163.11:3011/health >/dev/null && exit 0; sleep 5; done; exit 1"
EOF
  # Superseded ad-hoc gate (MDDB-only) — dep-gate.conf covers both deps.
  rm -f "$drop_dir/mddb-gate.conf"
done

systemctl --user daemon-reload
echo "dep-gate installed: ${#UNITS[@]} units (${UNITS[*]})"
