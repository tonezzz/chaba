#!/bin/bash
#
# Chaba backup manager — backs up tony-dell Postgres/volumes and tony-omen
# configs/docs to GoogleDrive via rclone.
#

set -uo pipefail

# --- configuration ---------------------------------------------------------
REMOTE_ROOT='gdrive:/Tony AI/backup/chaba'
DAILY_ROOT="$REMOTE_ROOT/daily"
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_ID="chaba-$BACKUP_DATE"
WORK_DIR=$(mktemp -d)
REPO_DIR="/home/tony/CascadeProjects/chaba"
BACKUP_LOG="/var/log/chaba-backup.log"
STATE_FILE="/home/tony/var/chaba/backup-state.json"
STATE_DIR=$(dirname "$STATE_FILE")

DAILY_RETENTION_DAYS=30
WEEKLY_RETENTION_WEEKS=12
MONTHLY_RETENTION_MONTHS=6

SECRETS_FILE="/home/tony/.config/secrets/chaba-backup.env"
if [ -f "$SECRETS_FILE" ]; then
  # shellcheck disable=SC1090
  set -a
  source "$SECRETS_FILE"
  set +a
fi

if [ -z "${CHABA_BACKUP_DB_PASSWORD:-}" ]; then
  echo "ERROR: CHABA_BACKUP_DB_PASSWORD not set. Configure $SECRETS_FILE" >&2
  exit 1
fi

# --- helpers ---------------------------------------------------------------
log() {
  local level="$1"
  shift
  local msg="$*"
  local ts
  ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[$ts] [$level] $msg" | tee -a "$BACKUP_LOG" >/dev/null
}

error_exit() {
  log "ERROR" "$1"
  exit 1
}

cleanup() {
  if [ -d "$WORK_DIR" ]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

# --- prerequisites ---------------------------------------------------------
check_prerequisites() {
  log "INFO" "Checking prerequisites..."

  if ! command -v rclone &>/dev/null; then
    error_exit "rclone not found"
  fi

  if ! command -v ssh &>/dev/null; then
    error_exit "ssh not found"
  fi

  if ! ssh -o BatchMode=yes -o ConnectTimeout=10 tony-dell 'hostname' >/dev/null 2>&1; then
    error_exit "Cannot reach tony-dell via ssh"
  fi

  log "INFO" "Prerequisites OK"
}

# --- postgres --------------------------------------------------------------
backup_database() {
  log "INFO" "Starting PostgreSQL backup from tony-dell..."

  local local_file="$WORK_DIR/postgres_${BACKUP_DATE}.sql.gz"
  local remote_path="$DAILY_ROOT/postgres_${BACKUP_DATE}.sql.gz"
  local start end duration size

  start=$(date +%s)

  if ! ssh -o BatchMode=yes tony-dell \
    "PGPASSWORD='${CHABA_BACKUP_DB_PASSWORD}' docker exec -e PGPASSWORD='${CHABA_BACKUP_DB_PASSWORD}' chaba-postgres-16 pg_dump -U chaba -d chaba" \
    | gzip > "$local_file"; then
    log "ERROR" "PostgreSQL dump from tony-dell failed"
    return 1
  fi

  end=$(date +%s)
  duration=$((end - start))
  size=$(stat -c %s "$local_file")

  if [ "$size" -lt 100 ]; then
    log "ERROR" "PostgreSQL backup is too small: $size bytes"
    return 1
  fi

  if ! gzip -t "$local_file" >/dev/null 2>&1; then
    log "ERROR" "PostgreSQL backup gzip test failed"
    return 1
  fi

  if ! rclone copyto "$local_file" "$remote_path"; then
    log "ERROR" "rclone copyto of PostgreSQL backup failed"
    return 1
  fi

  log "INFO" "PostgreSQL backup uploaded to $remote_path (${size} bytes, ${duration}s)"
}

# --- docker volumes --------------------------------------------------------
backup_volumes() {
  log "INFO" "Starting Docker volume backup from tony-dell..."

  local volumes=("postgres_data" "redis_data" "weaviate_data")
  local local_dir="$WORK_DIR/volumes_${BACKUP_DATE}"
  local remote_dir="$DAILY_ROOT/volumes_${BACKUP_DATE}"
  mkdir -p "$local_dir"

  local all_ok=1
  for vol in "${volumes[@]}"; do
    local local_file="$local_dir/${vol}.tar.gz"
    log "INFO" "Backing up volume: $vol"

    if ! ssh -o BatchMode=yes tony-dell \
      "docker run --rm -v '${vol}:/data' alpine tar czf - -C /data ." > "$local_file"; then
      log "ERROR" "Volume $vol backup via ssh failed"
      all_ok=0
      continue
    fi

    if [ ! -s "$local_file" ]; then
      log "ERROR" "Volume $vol backup file is empty"
      all_ok=0
      continue
    fi

    if ! tar -tzf "$local_file" >/dev/null 2>&1; then
      log "ERROR" "Volume $vol tar integrity check failed"
      all_ok=0
      continue
    fi

    if ! rclone copy "$local_file" "$remote_dir"; then
      log "ERROR" "rclone copy for volume $vol failed"
      all_ok=0
      continue
    fi

    log "INFO" "Volume $vol backed up to $remote_dir"
  done

  if [ "$all_ok" -eq 0 ]; then
    return 1
  fi

  log "INFO" "Docker volume backups completed"
}

# --- local configuration ---------------------------------------------------
backup_configs() {
  log "INFO" "Starting configuration backup..."

  local local_dir="$WORK_DIR/configs_${BACKUP_DATE}"
  local remote_dir="$DAILY_ROOT/configs_${BACKUP_DATE}"
  mkdir -p "$local_dir"

  if [ -d "$REPO_DIR/stacks" ]; then
    tar czf "$local_dir/stacks.tar.gz" -C "$REPO_DIR" stacks
    log "INFO" "Backed up stacks directory"
  fi

  if [ -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env" "$local_dir/"
    log "INFO" "Backed up .env file"
  fi

  if [ -f "$REPO_DIR/docker-compose.yml" ]; then
    cp "$REPO_DIR/docker-compose.yml" "$local_dir/"
    log "INFO" "Backed up docker-compose.yml"
  fi

  if [ -d "$REPO_DIR/docs/ssot" ]; then
    tar czf "$local_dir/ssot.tar.gz" -C "$REPO_DIR/docs" ssot
    log "INFO" "Backed up docs/ssot directory"
  fi

  if [ -d "$REPO_DIR/systemd" ]; then
    tar czf "$local_dir/systemd.tar.gz" -C "$REPO_DIR" systemd
    log "INFO" "Backed up systemd directory"
  fi

  if ! rclone copy "$local_dir" "$remote_dir"; then
    log "ERROR" "rclone copy of configuration backup failed"
    return 1
  fi

  log "INFO" "Configuration backup uploaded to $remote_dir"
}

# --- local documentation ---------------------------------------------------
backup_docs() {
  log "INFO" "Starting documentation backup..."

  local local_dir="$WORK_DIR/docs_${BACKUP_DATE}"
  local remote_dir="$DAILY_ROOT/docs_${BACKUP_DATE}"
  mkdir -p "$local_dir"

  if [ -d "$REPO_DIR/docs" ]; then
    tar czf "$local_dir/docs.tar.gz" -C "$REPO_DIR" docs
    log "INFO" "Backed up docs directory"
  else
    log "WARN" "Documentation directory not found: $REPO_DIR/docs"
  fi

  if ! rclone copy "$local_dir" "$remote_dir"; then
    log "ERROR" "rclone copy of documentation backup failed"
    return 1
  fi

  log "INFO" "Documentation backup uploaded to $remote_dir"
}

# --- rotation --------------------------------------------------------------
extract_ts() {
  # Pull YYYYMMDD_HHMMSS out of a backup name and strip the underscore.
  echo "$1" | grep -oE '[0-9]{8}_[0-9]{6}' | tr -d '_' | head -n1
}

rotate_daily() {
  log "INFO" "Rotating daily backups older than $DAILY_RETENTION_DAYS days..."
  local rc=0
  local cutoff
  cutoff=$(date -d "$DAILY_RETENTION_DAYS days ago" +%Y%m%d%H%M%S)

  local entry
  while IFS= read -r entry; do
    [ -z "$entry" ] && continue
    local ts
    ts=$(extract_ts "$entry")
    [ -z "$ts" ] && continue

    if [ "$ts" -lt "$cutoff" ]; then
      local full="$DAILY_ROOT/$entry"
      if [[ "$entry" == */ ]]; then
        if ! rclone purge "$full"; then
          log "WARN" "Failed to purge old daily directory: $full"
          rc=1
        else
          log "INFO" "Purged old daily directory: $full"
        fi
      else
        if ! rclone deletefile "$full"; then
          log "WARN" "Failed to delete old daily file: $full"
          rc=1
        else
          log "INFO" "Deleted old daily file: $full"
        fi
      fi
    fi
  done < <(rclone lsf "$DAILY_ROOT" 2>/dev/null)

  return $rc
}

rotate_weekly() {
  log "INFO" "Rotating weekly backups older than $WEEKLY_RETENTION_WEEKS weeks..."
  local rc=0
  local cutoff
  cutoff=$(date -d "$WEEKLY_RETENTION_WEEKS weeks ago" +%Y%U)

  local entry
  while IFS= read -r entry; do
    [ -z "$entry" ] && continue
    [[ "$entry" == week_* ]] || continue
    local wk
    wk=$(echo "$entry" | grep -oE '[0-9]{6}' | head -n1)
    [ -z "$wk" ] && continue

    if [ "$wk" -lt "$cutoff" ]; then
      local full="$REMOTE_ROOT/weekly/${entry%/}"
      if ! rclone purge "$full"; then
        log "WARN" "Failed to purge old weekly: $full"
        rc=1
      else
        log "INFO" "Purged old weekly: $full"
      fi
    fi
  done < <(rclone lsf "$REMOTE_ROOT/weekly" 2>/dev/null)

  return $rc
}

rotate_monthly() {
  log "INFO" "Rotating monthly backups older than $MONTHLY_RETENTION_MONTHS months..."
  local rc=0
  local cutoff
  cutoff=$(date -d "$MONTHLY_RETENTION_MONTHS months ago" +%Y%m)

  local entry
  while IFS= read -r entry; do
    [ -z "$entry" ] && continue
    [[ "$entry" == month_* ]] || continue
    local mon
    mon=$(echo "$entry" | grep -oE '[0-9]{6}' | head -n1)
    [ -z "$mon" ] && continue

    if [ "$mon" -lt "$cutoff" ]; then
      local full="$REMOTE_ROOT/monthly/${entry%/}"
      if ! rclone purge "$full"; then
        log "WARN" "Failed to purge old monthly: $full"
        rc=1
      else
        log "INFO" "Purged old monthly: $full"
      fi
    fi
  done < <(rclone lsf "$REMOTE_ROOT/monthly" 2>/dev/null)

  return $rc
}

rotate_backups() {
  log "INFO" "Starting remote backup rotation..."
  local rc=0

  rotate_daily || rc=1
  rotate_weekly || rc=1
  rotate_monthly || rc=1

  log "INFO" "Rotation completed"
  return $rc
}

# --- verification ----------------------------------------------------------
verify_backups() {
  log "INFO" "Verifying uploaded backups..."
  local rc=0

  if ! rclone lsf "$DAILY_ROOT/postgres_${BACKUP_DATE}.sql.gz" >/dev/null 2>&1; then
    log "ERROR" "Remote postgres backup not found"
    rc=1
  fi

  if [ "$(rclone lsf "$DAILY_ROOT/volumes_${BACKUP_DATE}" 2>/dev/null | wc -l)" -lt 1 ]; then
    log "ERROR" "Remote volume backup directory not found or empty"
    rc=1
  fi

  if [ "$(rclone lsf "$DAILY_ROOT/configs_${BACKUP_DATE}" 2>/dev/null | wc -l)" -lt 1 ]; then
    log "ERROR" "Remote configuration backup directory not found or empty"
    rc=1
  fi

  if [ "$(rclone lsf "$DAILY_ROOT/docs_${BACKUP_DATE}" 2>/dev/null | wc -l)" -lt 1 ]; then
    log "ERROR" "Remote documentation backup directory not found or empty"
    rc=1
  fi

  return $rc
}

# --- report ----------------------------------------------------------------
generate_backup_report() {
  local status=$1
  local report_file="$WORK_DIR/backup_report_${BACKUP_DATE}.txt"

  {
    echo "Chaba Infrastructure Backup Report"
    echo "=================================="
    echo "Backup ID: $BACKUP_ID"
    echo "Date:      $(date)"
    echo "Status:    $([ "$status" -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')"
    echo "Remote:    $REMOTE_ROOT"
    echo ""
    echo "Daily components:"
    echo "  $DAILY_ROOT/postgres_${BACKUP_DATE}.sql.gz"
    echo "  $DAILY_ROOT/volumes_${BACKUP_DATE}/"
    echo "  $DAILY_ROOT/configs_${BACKUP_DATE}/"
    echo "  $DAILY_ROOT/docs_${BACKUP_DATE}/"
  } > "$report_file"

  if ! rclone copyto "$report_file" "$REMOTE_ROOT/logs/backup_report_${BACKUP_DATE}.txt"; then
    log "WARN" "Backup report upload failed"
  else
    log "INFO" "Backup report uploaded"
  fi
}

# --- state -----------------------------------------------------------------
write_state() {
  local status=$1
  local ts
  ts=$(date -Iseconds)
  local state_status
  state_status=$([ "$status" -eq 0 ] && echo "success" || echo "failed")

  mkdir -p "$STATE_DIR"

  if command -v jq &>/dev/null; then
    jq -n \
      --arg id "$BACKUP_ID" \
      --arg ts "$ts" \
      --arg st "$state_status" \
      --arg date "$BACKUP_DATE" \
      --arg root "$REMOTE_ROOT" \
      --arg daily "$DAILY_ROOT" \
      --arg pg "daily/postgres_${BACKUP_DATE}.sql.gz" \
      --arg vol "daily/volumes_${BACKUP_DATE}" \
      --arg cfg "daily/configs_${BACKUP_DATE}" \
      --arg doc "daily/docs_${BACKUP_DATE}" \
      '{
        backup_id: $id,
        timestamp: $ts,
        status: $st,
        backup_date: $date,
        remote_root: $root,
        daily_path: $daily,
        components: {
          postgres: $pg,
          volumes: $vol,
          configs: $cfg,
          docs: $doc
        }
      }' > "$STATE_FILE"
  else
    cat > "$STATE_FILE" <<EOF
{
  "backup_id": "$BACKUP_ID",
  "timestamp": "$ts",
  "status": "$state_status",
  "backup_date": "$BACKUP_DATE",
  "remote_root": "$REMOTE_ROOT",
  "daily_path": "$DAILY_ROOT",
  "components": {
    "postgres": "daily/postgres_${BACKUP_DATE}.sql.gz",
    "volumes": "daily/volumes_${BACKUP_DATE}",
    "configs": "daily/configs_${BACKUP_DATE}",
    "docs": "daily/docs_${BACKUP_DATE}"
  }
}
EOF
  fi
}

# --- main ------------------------------------------------------------------
main() {
  local backup_type="${1:-full}"

  log "INFO" "=========================================="
  log "INFO" "Starting Chaba backup: $backup_type (id=$BACKUP_ID)"
  log "INFO" "=========================================="

  check_prerequisites
  mkdir -p "$WORK_DIR"

  local backup_failed=0

  case "$backup_type" in
    database)
      backup_database || backup_failed=1
      ;;
    volumes)
      backup_volumes || backup_failed=1
      ;;
    configs)
      backup_configs || backup_failed=1
      ;;
    docs)
      backup_docs || backup_failed=1
      ;;
    full)
      backup_database || backup_failed=1
      backup_volumes || backup_failed=1
      backup_configs || backup_failed=1
      backup_docs || backup_failed=1

      if [ "$backup_failed" -eq 0 ]; then
        rotate_backups || backup_failed=1
      fi

      if [ "$backup_failed" -eq 0 ]; then
        verify_backups || backup_failed=1
      fi
      ;;
    *)
      log "ERROR" "Unknown backup type: $backup_type"
      backup_failed=1
      ;;
  esac

  generate_backup_report $backup_failed
  write_state $backup_failed

  if [ "$backup_failed" -eq 0 ]; then
    log "INFO" "Backup completed successfully"
    return 0
  else
    log "ERROR" "Backup completed with failures"
    return 1
  fi
}

main "$@"
