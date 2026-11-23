#!/usr/bin/env bash
# mddb-backup-offload — archive idc03's ~/mddb-backups to a remote host
# and keep only the newest copies locally (card
# storage-rebalance-underused, 2026-11-23).
#
# Why: idc03 / is ~91% and growing ~6 GiB/day; ~/mddb-backups was ~59G.
# idc02 sits at ~46% with ~160 GiB free and already runs mddb follower +
# its own backup tier — it is the declared archive target. This script
# is the safe middle layer: mddb-backup.sh keeps landing + verifying
# backups locally (its headroom guard unchanged), then this runs after
# it and ships every .db.gz to the remote, pruning local copies beyond
# KEEP_LOCAL *per instance* only after the remote copy is confirmed to
# exist with the same size. A failed sync never deletes a byte.
#
# Usage:
#   mddb-backup-offload.sh             # sync + prune (locked, one at a time)
#   mddb-backup-offload.sh --dry-run   # report what would move, touch nothing
#
# Suggested wiring (pending Tony's go): ExecStartPost=-%h/bin/mddb-backup-offload.sh
# on mddb-backup.service, or its own OnCalendar 15min after mddb-backup.timer.
#
# Env (MDDB_BACKUP_OFFLOAD_* prefix; BK/INSTANCES shared with
# mddb-backup.sh so the same overrides apply):
#   MDDB_BACKUP_DIR                 default ~/mddb-backups
#   MDDB_BACKUP_INSTANCES           default "mddb:11023 mddb-ops:11026 mddb-cms:11027"
#   MDDB_BACKUP_OFFLOAD_TARGET      default idc02:~/mddb-backups-idc03
#   MDDB_BACKUP_OFFLOAD_KEEP_LOCAL  default 1  (newest-N kept per instance)
#   MDDB_BACKUP_OFFLOAD_MIN_FREE_GB default 20 (remote free floor before send)
#   MDDB_BACKUP_BOARD_API           default http://127.0.0.1:8787
set -euo pipefail

BK="${MDDB_BACKUP_DIR:-$HOME/mddb-backups}"
INSTANCES="${MDDB_BACKUP_INSTANCES:-mddb:11023 mddb-ops:11026 mddb-cms:11027}"
TARGET="${MDDB_BACKUP_OFFLOAD_TARGET:-idc02:~/mddb-backups-idc03}"
KEEP_LOCAL="${MDDB_BACKUP_OFFLOAD_KEEP_LOCAL:-1}"
MIN_FREE_GB="${MDDB_BACKUP_OFFLOAD_MIN_FREE_GB:-20}"
BOARD_API="${MDDB_BACKUP_BOARD_API:-http://127.0.0.1:8787}"
LOCK=/tmp/mddb-backup-offload.lock
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

RHOST="${TARGET%%:*}"
RPATH="${TARGET#*:}"

log() { echo "[$(date '+%F %T')] $*"; }

alert() {
  local msg="mddb-backup-offload idc03 $(date '+%F %T'): $*"
  log "ALERT: $msg"
  BOARD_API="$BOARD_API" ALERT_MSG="$msg" python3 - <<'PY' || true
import json, os, urllib.request
api, msg = os.environ["BOARD_API"], os.environ["ALERT_MSG"]
for path, body in (("/comment", {"id": "timer-alert-idc03-mddb-backup",
                                "from": "chaba", "text": msg}),
                   ("/inbox", {"text": msg,
                               "label": "mddb-backup-offload failure on idc03",
                               "priority": "medium",
                               "tags": ["ops", "mddb", "backup"]})):
    try:
        req = urllib.request.Request(api + path,
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"board-api {path} failed: {e}", file=__import__("sys").stderr)
PY
}

exec 9>"$LOCK"
flock -n 9 || { log "another offload is running — exit"; exit 0; }

# ---- build the local offload list -------------------------------------
# Every "$c"-2*.db.gz except the newest KEEP_LOCAL per instance is
# offload-eligible; the newest stay local for fast restore.
declare -A KEEP=()
for pair in $INSTANCES; do
  c="${pair%%:*}"
  mapfile -t files < <(ls -1 "$BK/$c"-2*.db.gz 2>/dev/null | sort)
  n=${#files[@]}
  for ((i = n - KEEP_LOCAL; i < n; i++)); do
    [ "$i" -ge 0 ] && KEEP["${files[$i]}"]=1
  done
done

eligible=()
while IFS= read -r f; do
  [ -n "${KEEP[$f]:-}" ] || eligible+=("$f")
done < <(find "$BK" -maxdepth 1 -name '*-2*.db.gz' | sort)

if [ "${#eligible[@]}" -eq 0 ]; then
  log "nothing eligible — local set already <= KEEP_LOCAL=$KEEP_LOCAL per instance"
  exit 0
fi

bytes=0
for f in "${eligible[@]}"; do
  b=$(stat -c %s "$f" 2>/dev/null || echo 0)
  bytes=$((bytes + b))
done
log "eligible: ${#eligible[@]} files, $((bytes / 1024 / 1024 / 1024)) GiB -> $TARGET"

# ---- remote headroom guard ---------------------------------------------
rdir_abs=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$RHOST" \
  "cd $RPATH 2>/dev/null && pwd" 2>/dev/null) || true
if [ -z "$rdir_abs" ] && [ "$DRY" = 0 ]; then
  log "remote dir $RPATH missing on $RHOST — creating"
  ssh -o BatchMode=yes "$RHOST" "mkdir -p $RPATH"
  rdir_abs=$(ssh -o BatchMode=yes "$RHOST" "cd $RPATH && pwd")
fi
need_kb=$(( bytes / 1024 + MIN_FREE_GB * 1024 * 1024 ))
free_kb=""
[ -n "$rdir_abs" ] && free_kb=$(ssh -o BatchMode=yes "$RHOST" \
  "df -kP $rdir_abs" | awk 'NR==2 {print $4}')

# ---- ship + verify + prune ----------------------------------------------
if [ "$DRY" = 1 ]; then
  printf 'DRY: %s\n' "${eligible[@]}"
  log "dry-run — remote free ${free_kb:+$((${free_kb:-0}/1024/1024))G}" \
    "need $((need_kb/1024/1024))G; no transfer, no deletes"
  exit 0
fi

if [ -z "$free_kb" ] || [ "$free_kb" -lt "$need_kb" ]; then
  alert "SKIP — remote headroom: $((${free_kb:-0}/1024/1024))G free <" \
    "$((need_kb/1024/1024))G needed on $RHOST"
  exit 1
fi

listfile=$(mktemp)
trap 'rm -f "$listfile"' EXIT
( cd "$BK" && printf '%s\n' "${eligible[@]#$BK/}" >"$listfile" )

if ! rsync -a --partial --files-from="$listfile" "$BK/" "$RHOST:$rdir_abs/"; then
  alert "rsync to $TARGET failed — nothing pruned locally"
  exit 1
fi

# Prune only files confirmed present remotely with the same size.
remote_listing=$(mktemp)
trap 'rm -f "$listfile" "$remote_listing"' EXIT
ssh -o BatchMode=yes "$RHOST" "cd $rdir_abs && ls -l" >"$remote_listing"

pruned=0
for f in "${eligible[@]}"; do
  base=$(basename "$f")
  lsize=$(stat -c %s "$f")
  rsize=$(awk -v n="$base" '$NF==n {print $5}' "$remote_listing" | tail -1)
  if [ "${rsize:-0}" = "$lsize" ] && [ "$lsize" -gt 0 ]; then
    rm -f "$f" && pruned=$((pruned + 1))
    log "offloaded+pruned: $base"
  else
    log "KEEP $base — remote copy missing/mismatched (local $lsize vs remote ${rsize:-none})"
  fi
done

log "done — pruned $pruned/${#eligible[@]}, $BK now $(du -sh "$BK" | cut -f1)"
