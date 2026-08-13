#!/bin/bash
#
# Automated Backup System for Chaba Infrastructure
# Provides comprehensive backup automation with rotation, verification, and monitoring
#

set -euo pipefail

# Configuration
BACKUP_ROOT="/home/tony/GoogleDrive/Tony AI/backup/chaba"
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_LOG="/var/log/chaba-backup.log"
BACKUP_RETENTION_DAYS=30
BACKUP_RETENTION_WEEKS=12
BACKUP_RETENTION_MONTHS=6

# Backup types
BACKUP_TYPES=("database" "docker-volumes" "configurations" "documentation")

# Create backup directories (handle existing gracefully)
mkdir -p "$BACKUP_ROOT/daily" 2>/dev/null || true
mkdir -p "$BACKUP_ROOT/weekly" 2>/dev/null || true
mkdir -p "$BACKUP_ROOT/monthly" 2>/dev/null || true
mkdir -p "$BACKUP_ROOT/logs" 2>/dev/null || true
mkdir -p "$(dirname "$BACKUP_LOG")" 2>/dev/null || true

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$BACKUP_LOG"
}

# Error handling
error_exit() {
    log "ERROR" "$1"
    exit 1
}

# Check prerequisites
check_prerequisites() {
    log "INFO" "Checking backup prerequisites..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        error_exit "Docker not found - required for volume backups"
    fi
    
    # Check PostgreSQL client
    if ! command -v docker &> /dev/null; then
        error_exit "Docker not found - required for database backups"
    fi
    
    # Check disk space
    local available_space=$(df -BG "$BACKUP_ROOT" | awk 'NR==2 {print $4}' | sed 's/G//')
    if [ "$available_space" -lt 10 ]; then
        log "WARN" "Low disk space: ${available_space}GB available"
    fi
    
    log "INFO" "Prerequisites check completed"
}

# PostgreSQL database backup
backup_database() {
    log "INFO" "Starting PostgreSQL database backup..."
    
    local backup_file="$BACKUP_ROOT/daily/postgres_${BACKUP_DATE}.sql.gz"
    local container_name="postgres"
    
    # Check if PostgreSQL container is running
    if ! docker ps | grep -q "$container_name"; then
        log "ERROR" "PostgreSQL container not running"
        return 1
    fi
    
    # Perform backup
    if docker exec "$container_name" pg_dump -U chaba chaba | gzip > "$backup_file"; then
        local backup_size=$(du -h "$backup_file" | cut -f1)
        log "INFO" "PostgreSQL backup completed: $backup_file ($backup_size)"
        
        # Verify backup integrity
        if gzip -t "$backup_file" 2>/dev/null; then
            log "INFO" "PostgreSQL backup integrity verified"
            return 0
        else
            log "ERROR" "PostgreSQL backup integrity check failed"
            rm -f "$backup_file"
            return 1
        fi
    else
        log "ERROR" "PostgreSQL backup failed"
        return 1
    fi
}

# Docker volumes backup
backup_docker_volumes() {
    log "INFO" "Starting Docker volumes backup..."

    local volumes=("postgres_data" "redis_data" "weaviate_data")
    local local_backup_dir="/tmp/chaba_volumes_${BACKUP_DATE}"
    local final_backup_dir="$BACKUP_ROOT/daily/volumes_${BACKUP_DATE}"

    # Use local temporary directory for Docker backups (FUSE mount compatibility)
    mkdir -p "$local_backup_dir"
    mkdir -p "$final_backup_dir"

    for volume in "${volumes[@]}"; do
        log "INFO" "Backing up volume: $volume"

        local volume_backup="$local_backup_dir/${volume}.tar.gz"

        # Create temporary container for backup to local directory
        if docker run --rm -v "$volume:/volume_data" -v "$local_backup_dir:/backup" \
            alpine tar czf "/backup/${volume}.tar.gz" -C /volume_data .; then
            local backup_size=$(du -h "$volume_backup" | cut -f1)
            log "INFO" "Volume backup completed: $volume ($backup_size)"

            # Copy to Google Drive after successful backup
            cp "$volume_backup" "$final_backup_dir/"
            log "INFO" "Volume backup copied to Google Drive: $volume"
        else
            log "ERROR" "Volume backup failed: $volume"
        fi
    done

    # Cleanup local temporary directory
    rm -rf "$local_backup_dir"

    log "INFO" "Docker volumes backup completed"
}

# Configuration files backup
backup_configurations() {
    log "INFO" "Starting configuration files backup..."

    local local_backup_dir="/tmp/chaba_configs_${BACKUP_DATE}"
    local final_backup_dir="$BACKUP_ROOT/daily/configs_${BACKUP_DATE}"

    # Use local temporary directory for compatibility
    mkdir -p "$local_backup_dir"
    mkdir -p "$final_backup_dir"
    
    # Docker Compose files
    local compose_dirs=("/home/tony/CascadeProjects/chaba/stacks/web")
    for dir in "${compose_dirs[@]}"; do
        if [ -d "$dir" ]; then
            local dir_name=$(basename "$dir")
            tar czf "$local_backup_dir/${dir_name}.tar.gz" -C "$(dirname "$dir")" "$dir_name"
            log "INFO" "Backed up: $dir"
        fi
    done

    # Environment files
    local env_files=(
        "/home/tony/CascadeProjects/chaba/stacks/web/.env"
        "/home/tony/CascadeProjects/chaba/stacks/web/.env.production"
    )

    for env_file in "${env_files[@]}"; do
        if [ -f "$env_file" ]; then
            cp "$env_file" "$local_backup_dir/"
            log "INFO" "Backed up: $env_file"
        fi
    done

    # SSOT files
    local ssot_dir="/home/tony/CascadeProjects/chaba/docs/ssot"
    if [ -d "$ssot_dir" ]; then
        tar czf "$local_backup_dir/ssot.tar.gz" -C "$(dirname "$ssot_dir")" "ssot"
        log "INFO" "Backed up: SSOT files"
    fi

    # System configuration
    local systemd_dir="/home/tony/CascadeProjects/chaba/systemd"
    if [ -d "$systemd_dir" ]; then
        tar czf "$local_backup_dir/systemd.tar.gz" -C "$(dirname "$systemd_dir")" "systemd"
        log "INFO" "Backed up: Systemd files"
    fi

    # Copy all configuration backups to Google Drive
    cp -r "$local_backup_dir"/* "$final_backup_dir/"
    log "INFO" "Configuration backups copied to Google Drive"

    # Cleanup local temporary directory
    rm -rf "$local_backup_dir"

    log "INFO" "Configuration files backup completed"
}

# Documentation backup
backup_documentation() {
    log "INFO" "Starting documentation backup..."

    local local_backup_dir="/tmp/chaba_docs_${BACKUP_DATE}"
    local final_backup_dir="$BACKUP_ROOT/daily/docs_${BACKUP_DATE}"

    # Use local temporary directory for compatibility
    mkdir -p "$local_backup_dir"
    mkdir -p "$final_backup_dir"

    local docs_dir="/home/tony/CascadeProjects/chaba/docs"
    if [ -d "$docs_dir" ]; then
        tar czf "$local_backup_dir/docs.tar.gz" -C "$(dirname "$docs_dir")" "docs"
        local backup_size=$(du -h "$local_backup_dir/docs.tar.gz" | cut -f1)
        log "INFO" "Documentation backup completed ($backup_size)"

        # Copy to Google Drive
        cp "$local_backup_dir/docs.tar.gz" "$final_backup_dir/"
        log "INFO" "Documentation backup copied to Google Drive"
    else
        log "WARN" "Documentation directory not found"
    fi

    # Cleanup local temporary directory
    rm -rf "$local_backup_dir"
}

# Backup rotation
rotate_backups() {
    log "INFO" "Starting backup rotation..."
    
    # Daily backups - keep 30 days
    find "$BACKUP_ROOT/daily" -name "postgres_*.sql.gz" -mtime +$BACKUP_RETENTION_DAYS -delete
    find "$BACKUP_ROOT/daily" -name "volumes_*.tar.gz" -mtime +$BACKUP_RETENTION_DAYS -delete
    find "$BACKUP_ROOT/daily" -name "configs_*.tar.gz" -mtime +$BACKUP_RETENTION_DAYS -delete
    find "$BACKUP_ROOT/daily" -name "docs_*.tar.gz" -mtime +$BACKUP_RETENTION_DAYS -delete
    
    # Weekly backups - keep 12 weeks
    find "$BACKUP_ROOT/weekly" -name "*.tar.gz" -mtime +$((BACKUP_RETENTION_WEEKS * 7)) -delete
    
    # Monthly backups - keep 6 months
    find "$BACKUP_ROOT/monthly" -name "*.tar.gz" -mtime +$((BACKUP_RETENTION_MONTHS * 30)) -delete
    
    log "INFO" "Backup rotation completed"
}

# Create weekly backup
create_weekly_backup() {
    local day_of_week=$(date +%u)
    
    if [ "$day_of_week" -eq 7 ]; then  # Sunday
        log "INFO" "Creating weekly backup..."
        
        local weekly_dir="$BACKUP_ROOT/weekly/week_$(date +%Y%U)"
        mkdir -p "$weekly_dir"
        
        # Copy latest daily backups to weekly
        cp -r "$BACKUP_ROOT/daily/"* "$weekly_dir/" 2>/dev/null || true
        
        log "INFO" "Weekly backup created: $weekly_dir"
    fi
}

# Create monthly backup
create_monthly_backup() {
    local day_of_month=$(date +%d)
    
    if [ "$day_of_month" -eq 1 ]; then  # First day of month
        log "INFO" "Creating monthly backup..."
        
        local monthly_dir="$BACKUP_ROOT/monthly/month_$(date +%Y%m)"
        mkdir -p "$monthly_dir"
        
        # Copy latest weekly backup to monthly
        local latest_weekly=$(ls -t "$BACKUP_ROOT/weekly" | head -1)
        if [ -n "$latest_weekly" ]; then
            cp -r "$BACKUP_ROOT/weekly/$latest_weekly/"* "$monthly_dir/" 2>/dev/null || true
            log "INFO" "Monthly backup created: $monthly_dir"
        fi
    fi
}

# Backup verification
verify_backups() {
    log "INFO" "Starting backup verification..."
    
    local verification_failed=0
    
    # Verify latest database backup
    local latest_db_backup=$(find "$BACKUP_ROOT/daily" -name "postgres_*.sql.gz" -type f 2>/dev/null | sort -r | head -1)
    if [ -n "$latest_db_backup" ]; then
        if gzip -t "$latest_db_backup" 2>/dev/null; then
            log "INFO" "Database backup verified: $latest_db_backup"
        else
            log "ERROR" "Database backup verification failed: $latest_db_backup"
            verification_failed=1
        fi
    fi

    # Verify latest volume backups
    local latest_volume_backup=$(find "$BACKUP_ROOT/daily" -name "*.tar.gz" -path "*/volumes_*" -type f 2>/dev/null | sort -r | head -1)
    if [ -n "$latest_volume_backup" ]; then
        if tar -tzf "$latest_volume_backup" > /dev/null 2>&1; then
            log "INFO" "Volume backup verified: $latest_volume_backup"
        else
            log "ERROR" "Volume backup verification failed: $latest_volume_backup"
            verification_failed=1
        fi
    fi
    
    if [ $verification_failed -eq 0 ]; then
        log "INFO" "All backups verified successfully"
    else
        log "ERROR" "Some backups failed verification"
    fi
    
    return $verification_failed
}

# Generate backup report
generate_backup_report() {
    local verification_status="${1:-0}"  # Default to success (0)
    log "INFO" "Generating backup report..."

    local report_file="$BACKUP_ROOT/logs/backup_report_${BACKUP_DATE}.txt"

    cat > "$report_file" << EOF
Chaba Infrastructure Backup Report
===================================
Date: $(date)
Backup ID: $BACKUP_DATE

Backup Summary:
---------------
EOF
    
    # Count backups by type (looking in subdirectories)
    local db_count=$(find "$BACKUP_ROOT/daily" -name "postgres_*.sql.gz" 2>/dev/null | wc -l)
    local volume_count=$(find "$BACKUP_ROOT/daily" -name "*.tar.gz" -path "*/volumes_*" 2>/dev/null | wc -l)
    local config_count=$(find "$BACKUP_ROOT/daily" -name "*.tar.gz" -path "*/configs_*" 2>/dev/null | wc -l)
    local docs_count=$(find "$BACKUP_ROOT/daily" -name "docs_*.tar.gz" 2>/dev/null | wc -l)
    
    cat >> "$report_file" << EOF
Database Backups: $db_count
Volume Backups: $volume_count
Configuration Backups: $config_count
Documentation Backups: $docs_count

Storage Usage:
--------------
EOF
    
    # Calculate storage usage
    local total_size=$(du -sh "$BACKUP_ROOT" | cut -f1)
    local daily_size=$(du -sh "$BACKUP_ROOT/daily" | cut -f1)
    local weekly_size=$(du -sh "$BACKUP_ROOT/weekly" | cut -f1)
    local monthly_size=$(du -sh "$BACKUP_ROOT/monthly" | cut -f1)
    
    cat >> "$report_file" << EOF
Total: $total_size
Daily: $daily_size
Weekly: $weekly_size
Monthly: $monthly_size

Retention Status:
-----------------
Daily backups: $BACKUP_RETENTION_DAYS days
Weekly backups: $BACKUP_RETENTION_WEEKS weeks
Monthly backups: $BACKUP_RETENTION_MONTHS months

Backup Status: $([ $verification_status -eq 0 ] && echo "SUCCESS" || echo "FAILED")
EOF
    
    log "INFO" "Backup report generated: $report_file"
}

# Send backup notification
send_notification() {
    local status="$1"
    local message="$2"
    
    log "INFO" "Backup notification: $status - $message"
    
    # Could integrate with notification system here
    # For now, just log the notification
}

# Main backup function
main() {
    local backup_type="${1:-full}"
    
    log "INFO" "=========================================="
    log "INFO" "Starting Chaba backup: $backup_type"
    log "INFO" "=========================================="
    
    check_prerequisites
    
    local backup_start=$(date +%s)
    local backup_failed=0
    
    case "$backup_type" in
        database)
            backup_database || backup_failed=1
            ;;
        volumes)
            backup_docker_volumes || backup_failed=1
            ;;
        configs)
            backup_configurations || backup_failed=1
            ;;
        docs)
            backup_documentation || backup_failed=1
            ;;
        full)
            backup_database || backup_failed=1
            backup_docker_volumes || backup_failed=1
            backup_configurations || backup_failed=1
            backup_documentation || backup_failed=1
            ;;
        *)
            error_exit "Unknown backup type: $backup_type"
            ;;
    esac
    
    # Perform rotation and verification for full backups
    if [ "$backup_type" = "full" ]; then
        rotate_backups
        create_weekly_backup
        create_monthly_backup
        verify_backups || backup_failed=1
        generate_backup_report $backup_failed
    fi
    
    local backup_end=$(date +%s)
    local backup_duration=$((backup_end - backup_start))
    
    if [ $backup_failed -eq 0 ]; then
        log "INFO" "Backup completed successfully in ${backup_duration}s"
        send_notification "SUCCESS" "Backup completed in ${backup_duration}s"
    else
        log "ERROR" "Backup failed after ${backup_duration}s"
        send_notification "FAILED" "Backup failed after ${backup_duration}s"
        exit 1
    fi
}

# Run main function
main "$@"