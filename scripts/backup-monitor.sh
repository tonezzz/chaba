#!/bin/bash
#
# Chaba backup monitor — verifies the latest backup set on GoogleDrive.
#

set -uo pipefail

# --- configuration ---------------------------------------------------------
STATE_FILE="/home/tony/var/chaba/backup-state.json"
BACKUP_LOG="/var/log/chaba-backup.log"
MONITOR_LOG="/var/log/chaba-backup-monitor.log"
DEFAULT_MAX_AGE_HOURS=36
MAX_AGE_HOURS=${BACKUP_MAX_AGE_HOURS:-$DEFAULT_MAX_AGE_HOURS}
REMOTE_ROOT='gdrive:/Tony AI/backup/chaba'

# --- helpers ---------------------------------------------------------------
log() {
  local level="$1"
  shift
  local msg="$*"
  local ts
  ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[$ts] [$level] $msg" | tee -a "$MONITOR_LOG" >/dev/null
}

# --- state -----------------------------------------------------------------
load_state() {
  if [ ! -f "$STATE_FILE" ]; then
    log "ERROR" "State file not found: $STATE_FILE"
    return 1
  fi

  if ! command -v jq &>/dev/null; then
    log "ERROR" "jq not found"
    return 1
  fi

  BACKUP_ID=$(jq -r '.backup_id // empty' "$STATE_FILE")
  BACKUP_TS=$(jq -r '.timestamp // empty' "$STATE_FILE")
  BACKUP_STATUS=$(jq -r '.status // empty' "$STATE_FILE")
  DAILY_PATH=$(jq -r '.daily_path // empty' "$STATE_FILE")
  PG_REMOTE=$(jq -r '.components.postgres // empty' "$STATE_FILE")
  VOLS_REMOTE=$(jq -r '.components.volumes // empty' "$STATE_FILE")
  CFG_REMOTE=$(jq -r '.components.configs // empty' "$STATE_FILE")
  DOCS_REMOTE=$(jq -r '.components.docs // empty' "$STATE_FILE")

  if [ -z "$BACKUP_ID" ] || [ -z "$BACKUP_TS" ]; then
    log "ERROR" "State file is missing required fields"
    return 1
  fi

  log "INFO" "Loaded state: backup_id=$BACKUP_ID, timestamp=$BACKUP_TS, status=$BACKUP_STATUS"
}

remote_size() {
  local path="$1"
  rclone ls "$path" 2>/dev/null | awk 'NR==1 {print $1}'
}

# --- checks ----------------------------------------------------------------
check_status() {
  log "INFO" "Checking backup status..."
  if [ "$BACKUP_STATUS" != "success" ]; then
    log "ERROR" "Latest backup did not report success: $BACKUP_STATUS"
    return 1
  fi
  log "INFO" "Backup status OK"
}

check_freshness() {
  log "INFO" "Checking backup freshness (threshold: ${MAX_AGE_HOURS}h)..."

  local now
  now=$(date +%s)
  local bt
  if ! bt=$(date -d "$BACKUP_TS" +%s 2>/dev/null); then
    log "ERROR" "Cannot parse timestamp $BACKUP_TS"
    return 1
  fi

  local age_hours=$(( (now - bt) / 3600 ))
  if [ "$age_hours" -gt "$MAX_AGE_HOURS" ]; then
    log "ERROR" "Latest backup is ${age_hours}h old (threshold: ${MAX_AGE_HOURS}h)"
    return 1
  fi

  log "INFO" "Freshness OK: ${age_hours}h old"
}

check_size() {
  log "INFO" "Checking backup sizes..."
  local rc=0

  local pg_path="$REMOTE_ROOT/$PG_REMOTE"
  local pg_size
  pg_size=$(remote_size "$pg_path")
  if [ -z "$pg_size" ] || [ "$pg_size" -lt 100 ]; then
    log "ERROR" "Postgres backup missing or too small: ${pg_size:-0} bytes"
    rc=1
  else
    log "INFO" "Postgres backup size OK: $pg_size bytes"
  fi

  for comp in "$VOLS_REMOTE" "$CFG_REMOTE" "$DOCS_REMOTE"; do
    local full="$REMOTE_ROOT/$comp"
    local first
    first=$(remote_size "$full")
    if [ -z "$first" ] || [ "${first:-0}" -lt 1 ]; then
      log "ERROR" "Component $comp missing or empty"
      rc=1
    else
      log "INFO" "Component $comp has content"
    fi
  done

  return $rc
}

check_integrity() {
  log "INFO" "Checking postgres backup integrity..."
  local pg_path="$REMOTE_ROOT/$PG_REMOTE"

  if ! rclone cat "$pg_path" 2>/dev/null | gzip -d - >/dev/null 2>&1; then
    log "ERROR" "Postgres backup gzip integrity check failed"
    return 1
  fi

  log "INFO" "Postgres backup integrity OK"
}

check_completeness() {
  log "INFO" "Checking backup completeness..."
  local rc=0

  for comp in "$PG_REMOTE" "$VOLS_REMOTE" "$CFG_REMOTE" "$DOCS_REMOTE"; do
    local full="$REMOTE_ROOT/$comp"
    local count
    count=$(rclone ls "$full" 2>/dev/null | wc -l)
    if [ "$count" -lt 1 ]; then
      log "ERROR" "Component $comp not found on remote"
      rc=1
    else
      log "INFO" "Component $comp found ($count object(s))"
    fi
  done

  return $rc
}

check_rotation() {
  log "INFO" "Checking backup rotation..."

  local old=0
  local cutoff
  cutoff=$(date -d "35 days ago" +%Y%m%d%H%M%S)

  local entry
  while IFS= read -r entry; do
    [ -z "$entry" ] && continue
    local ts
    ts=$(echo "$entry" | grep -oE '[0-9]{8}_[0-9]{6}' | tr -d '_' | head -n1)
    [ -z "$ts" ] && continue
    if [ "$ts" -lt "$cutoff" ]; then
      old=$((old + 1))
    fi
  done < <(rclone lsf "$DAILY_PATH" 2>/dev/null)

  if [ "$old" -gt 0 ]; then
    log "WARNING" "Found $old daily backup sets older than 35 days (rotation may not be working)"
    return 1
  fi

  log "INFO" "Rotation OK"
}

check_failures() {
  log "INFO" "Checking backup log for failures since latest backup..."

  local count
  count=$(python3 - "$BACKUP_LOG" "$BACKUP_TS" <<'PY'
import re, datetime, sys
log_path, last_ts = sys.argv[1:3]
try:
    cutoff = datetime.datetime.fromisoformat(last_ts).astimezone().replace(tzinfo=None)
except ValueError:
    cutoff = datetime.datetime.min
c = 0
try:
    with open(log_path) as f:
        for line in f:
            m = re.search(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', line)
            if not m:
                continue
            ts = datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
            if ts >= cutoff and 'ERROR' in line:
                c += 1
except FileNotFoundError:
    pass
print(c)
PY
)

  if [ "${count:-0}" -gt 0 ]; then
    log "ERROR" "Found $count ERROR entries since latest backup"
    return 1
  fi

  log "INFO" "No new errors since latest backup"
}

check_disk_space() {
  log "INFO" "Checking local disk space..."

  local avail
  avail=$(df -BG / | awk 'NR==2 {print $4}' | sed 's/G//')
  if [ "$avail" -lt 5 ]; then
    log "ERROR" "Low local disk space: ${avail}GB"
    return 1
  fi

  log "INFO" "Disk space OK: ${avail}GB free"
}

# --- main ------------------------------------------------------------------
main() {
  local check_type="${1:-all}"

  log "INFO" "=========================================="
  log "INFO" "Starting backup monitor: $check_type"
  log "INFO" "=========================================="

  load_state || exit 1

  local checks_passed=0
  local checks_failed=0

  run_check() {
    if "$@"; then
      checks_passed=$((checks_passed + 1))
    else
      checks_failed=$((checks_failed + 1))
    fi
  }

  case "$check_type" in
    status)       run_check check_status ;;
    freshness)    run_check check_freshness ;;
    size)         run_check check_size ;;
    integrity)    run_check check_integrity ;;
    completeness) run_check check_completeness ;;
    rotation)     run_check check_rotation ;;
    failures)     run_check check_failures ;;
    disk)         run_check check_disk_space ;;
    all)
      run_check check_status
      run_check check_freshness
      run_check check_size
      run_check check_integrity
      run_check check_completeness
      run_check check_rotation
      run_check check_failures
      run_check check_disk_space
      ;;
    *)
      echo "Usage: $0 {status|freshness|size|integrity|completeness|rotation|failures|disk|all}" >&2
      exit 1
      ;;
  esac

  log "INFO" "Monitor completed: $checks_passed passed, $checks_failed failed"

  if [ "$checks_failed" -gt 0 ]; then
    exit 1
  fi
}

main "$@"
