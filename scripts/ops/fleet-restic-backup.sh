#!/usr/bin/env bash
# fleet-restic-backup.sh — daily fleet restic backup to the tony-dell sdb repo.
# Canonical copy lives here (scripts/ops/); installed per-host at
# ~/.local/bin/fleet-restic-backup.sh and driven by the user unit
# fleet-restic-backup.service (timer: daily 05:15, Persistent=true).
#
# 2026-11-27 (OPS-1486, card restic-backup-intermittent-exit-fix-unpinned):
# the Persistent timer fires ~10-15s after boot, before Tailscale/routes are
# up, so restic died in ~1s with "Network is unreachable" to the sftp target
# (observed 11-23 06:46 and 11-27 09:06 — both post-boot catch-up runs).
# Fix: bounded wait-for-repo preflight + per-command retry/backoff, with
# DIAGNOSIS lines in ~/var/log/fleet-restic.log classifying the failure.
set -uo pipefail
set -a; . "$HOME/.config/secrets/restic-fleet.env"; set +a
LOG="$HOME/var/log/fleet-restic.log"; mkdir -p "$HOME/var/log"
exec >>"$LOG" 2>&1
echo "=== $(date -Is) start ==="

RESTIC="$HOME/.local/bin/restic"

# Bounded retry knobs (env-overridable for tests).
NET_WAIT="${FLEET_RESTIC_NET_WAIT:-180}"    # max s to wait for repo host pre-run
NET_POLL="${FLEET_RESTIC_NET_POLL:-10}"     # probe interval
ATTEMPTS="${FLEET_RESTIC_ATTEMPTS:-4}"      # tries per restic invocation
BACKOFF="${FLEET_RESTIC_BACKOFF:-15}"       # s, doubles per retry, capped 120

PATHS=()
for d in "$HOME/.config/secrets" "$HOME/.config/systemd" "$HOME/.config/containers" "$HOME/.config/devin" "$HOME/.local/bin" "$HOME/bin" "$HOME/.ssh"; do
  [ -d "$d" ] && PATHS+=("$d")
done

# sftp repo target, e.g. sftp:tony@tony-dell:/dell-backup/restic-fleet/<host>
SFTP_TARGET=""
if [[ "${RESTIC_REPOSITORY:-}" == sftp:*@* ]]; then
  SFTP_TARGET="${RESTIC_REPOSITORY#sftp:}"
  SFTP_TARGET="${SFTP_TARGET%%:*}"
fi

repo_host_up() {
  [ -n "$SFTP_TARGET" ] || return 0
  ssh -o ConnectTimeout=5 -o BatchMode=yes "$SFTP_TARGET" true >/dev/null 2>&1
}

# Preflight: absorb the post-boot window where Tailscale/routes aren't up yet.
if [ -n "$SFTP_TARGET" ]; then
  waited=0
  until repo_host_up; do
    if [ "$waited" -ge "$NET_WAIT" ]; then
      echo "DIAGNOSIS: repo host $SFTP_TARGET unreachable after ${waited}s — network/Tailscale still down; aborting (next timer run retries)"
      exit 1
    fi
    echo "repo host $SFTP_TARGET not reachable (${waited}s/${NET_WAIT}s) — post-boot Tailscale bring-up? waiting"
    sleep "$NET_POLL"; waited=$((waited + NET_POLL))
  done
  [ "$waited" -gt 0 ] && echo "repo host $SFTP_TARGET reachable after ${waited}s wait"
fi

diagnose() {
  # $1 = step label, $2 = captured output file
  if grep -qiE "network is unreachable|no route to host|connection timed out|connection refused|could not resolve|name or service not known|error receiving version packet|unable to open repository" "$2"; then
    echo "DIAGNOSIS[$1]: repo/network unreachable — transient drop or post-boot Tailscale not up yet"
  elif grep -qiE "already locked|repository is locked|lock.*exists" "$2"; then
    echo "DIAGNOSIS[$1]: repository lock conflict — check 'restic unlock' on the repo host"
  elif grep -qiE "wrong password|invalid password|password.*incorrect" "$2"; then
    echo "DIAGNOSIS[$1]: repo auth failure — check RESTIC_PASSWORD in restic-fleet.env"
  else
    echo "DIAGNOSIS[$1]: unclassified restic failure — see output above"
  fi
}

run_restic() {
  # $1 doubles as log label AND first restic arg (the subcommand)
  local label="$1" attempt=1 delay=$BACKOFF rc=0 out
  out="$(mktemp "$LOG.restic.XXXXXX")"
  while :; do
    echo "--- $label attempt $attempt/$ATTEMPTS $(date -Is) ---"
    if "$RESTIC" "$@" >"$out" 2>&1; then
      cat "$out"; rm -f "$out"; return 0
    else
      rc=$?
      cat "$out"
      diagnose "$label" "$out"
      if [ "$attempt" -ge "$ATTEMPTS" ]; then
        echo "FATAL: $label failed rc=$rc after $ATTEMPTS attempts"
        rm -f "$out"; return "$rc"
      fi
      echo "retrying $label in ${delay}s (attempt $((attempt+1))/$ATTEMPTS)"
      sleep "$delay"
      delay=$((delay * 2)); [ "$delay" -gt 120 ] && delay=120
      attempt=$((attempt + 1))
    fi
  done
}

run_restic backup "${PATHS[@]}" --exclude-caches --exclude "containers/*/data" --tag fleet-critical || exit $?
run_restic forget --tag fleet-critical --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune || exit $?

echo "=== $(date -Is) done ==="
