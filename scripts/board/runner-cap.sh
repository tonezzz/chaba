#!/usr/bin/env bash
# runner-cap — standard procedure for adjusting a dispatch host's
# runner-agent concurrency cap (and load gate) over ssh.
#
# Caps live in ~/.config/systemd/user/runner-agent.service Environment=
# lines (hand-provisioned). This script writes a drop-in override so the
# base unit stays untouched, reloads, and verifies the effective env.
#
#   runner-cap.sh <host> <cap> [max-load-pc]      # e.g. runner-cap.sh idc01 4 0.85
#   runner-cap.sh <host> show                     # current cap/labels/gate
#
# Safety ceiling: a Devin dispatch session costs ~3-4 GB RSS (node +
# python + tool children); cap is refused above floor(mem_total_gb / 3.5)
# unless --force is passed. RUNNER_MAX_LOAD_PC (0..1, 0=off) gates claims
# on load5/cpu — set ~0.85 on hosts that also serve production so a busy
# box yields the queue instead of stacking sessions into a crash.
#
# After changing a cap, mirror it in ssot.kanban.yml runner_fleet so the
# doc stays the source of truth (script prints a reminder).
set -euo pipefail

FORCE=0
[ "${1:-}" = "--force" ] && { FORCE=1; shift; }
HOST="${1:?host required}"; shift
ACTION="${1:-show}"
GATE="${2:-}"

remote() { ssh -o ConnectTimeout=8 "$HOST" "$@"; }

if [ "$ACTION" = "show" ]; then
  remote 'systemctl --user cat runner-agent.service 2>/dev/null | grep -E "^(Environment|ExecStart)" ; awk "/MemTotal/{printf \"mem_total_gb=%.1f\n\", \$2/1048576}" /proc/meminfo; awk "{printf \"load5=%.2f ncpu=%d\n\", \$2, $(getconf _NPROCESSORS_ONLN)}" /proc/loadavg' 2>/dev/null || true
  exit 0
fi

# Positional form: <host> <cap> [max-load-pc] — ACTION is the cap.
CAP="$ACTION"

[[ "$CAP" =~ ^[0-9]+$ ]] && [ "$CAP" -ge 0 ] || { echo "cap must be a non-negative int" >&2; exit 2; }

MEM_GB=$(remote 'awk "/MemTotal/{printf \"%.1f\", \$2/1048576}" /proc/meminfo')
CEIL=$(awk -v m="$MEM_GB" 'BEGIN{print int(m/3.5)}')
[ "$CEIL" -lt 1 ] && CEIL=1
if [ "$CAP" -gt "$CEIL" ] && [ "$FORCE" -ne 1 ]; then
  echo "refuse: cap $CAP > ceil $CEIL for ${MEM_GB}GB host (~3.5GB/session). --force to override." >&2
  exit 1
fi

GATE_LINE=""
if [ -n "$GATE" ]; then
  [[ "$GATE" =~ ^0?\.[0-9]+$|^1\.0$|^0$ ]] || { echo "max-load-pc must be 0..1.0" >&2; exit 2; }
  GATE_LINE="Environment=RUNNER_MAX_LOAD_PC=$GATE"
fi

remote bash -s <<EOF
set -euo pipefail
d="\$HOME/.config/systemd/user/runner-agent.service.d"
mkdir -p "\$d"
cat > "\$d/cap.conf" <<CONF
# Managed by chaba scripts/board/runner-cap.sh — do not hand-edit.
[Service]
Environment=RUNNER_CAP=$CAP
$GATE_LINE
CONF
systemctl --user daemon-reload
systemctl --user try-restart runner-agent.timer runner-agent.service 2>/dev/null || true
EOF

echo "== $HOST effective env now:"
remote 'systemctl --user cat runner-agent.service | grep Environment'
echo "NOTE: mirror the change in docs/ssot/kanban/ssot.kanban.yml runner_fleet"
