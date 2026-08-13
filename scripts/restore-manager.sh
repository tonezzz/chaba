#!/bin/bash
#
# Backup Restoration System for Chaba Infrastructure
# Provides safe restoration capabilities with verification
#

set -euo pipefail

# Configuration
BACKUP_ROOT="/home/tony/backups/chaba"
RESTORE_LOG="/var/log/chaba-restore.log"

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$RESTORE_LOG"
}

# Error handling
error_exit() {
    log "ERROR" "$1"
    exit 1
}

# List available backups
list_backups() {
    log "INFO" "Available backups:"
    
    echo "=== Daily Backups ==="
    ls -lh "$BACKUP_ROOT/daily/"*.{sql.gz,tar.gz} 2>/dev/null || echo "No daily backups found"
    
    echo ""
    echo "=== Weekly Backups ==="
    ls -lh "$BACKUP_ROOT/weekly/" 2>/dev/null || echo "No weekly backups found"
    
    echo ""
    echo "=== Monthly Backups ==="
    ls -lh "$BACKUP_ROOT/monthly/" 2>/dev/null || echo "No monthly backups found"
}

# Restore PostgreSQL database
restore_database() {
    local backup_file="$1"
    
    if [ ! -f "$backup_file" ]; then
        error_exit "Backup file not found: $backup_file"
    fi
    
    log "INFO" "Starting PostgreSQL database restoration from: $backup_file"
    
    local container_name="postgres"
    
    # Check if PostgreSQL container is running
    if ! docker ps | grep -q "$container_name"; then
        error_exit "PostgreSQL container not running"
    fi
    
    # Confirm restoration
    echo "WARNING: This will replace the current database!"
    read -p "Are you sure you want to proceed? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log "INFO" "Database restoration cancelled"
        return 1
    fi
    
    # Perform restoration
    if gunzip -c "$backup_file" | docker exec -i "$container_name" psql -U chaba chaba; then
        log "INFO" "Database restoration completed successfully"
        return 0
    else
        log "ERROR" "Database restoration failed"
        return 1
    fi
}

# Restore Docker volumes
restore_volumes() {
    local backup_dir="$1"
    
    if [ ! -d "$backup_dir" ]; then
        error_exit "Backup directory not found: $backup_dir"
    fi
    
    log "INFO" "Starting Docker volumes restoration from: $backup_dir"
    
    local volumes=("postgres_data" "redis_data" "weaviate_data")
    
    for volume in "${volumes[@]}"; do
        local volume_backup="$backup_dir/${volume}.tar.gz"
        
        if [ ! -f "$volume_backup" ]; then
            log "WARN" "Volume backup not found: $volume_backup"
            continue
        fi
        
        log "INFO" "Restoring volume: $volume"
        
        # Confirm restoration
        echo "WARNING: This will replace the current volume data!"
        read -p "Restore $volume? (yes/no): " confirm
        if [ "$confirm" != "yes" ]; then
            log "INFO" "Volume restoration cancelled: $volume"
            continue
        fi
        
        # Perform restoration
        if docker run --rm -v "$volume:/volume_data" -v "$backup_dir:/backup" \
            alpine tar xzf "/backup/${volume}.tar.gz" -C /volume_data; then
            log "INFO" "Volume restoration completed: $volume"
        else
            log "ERROR" "Volume restoration failed: $volume"
        fi
    done
    
    log "INFO" "Docker volumes restoration completed"
}

# Restore configurations
restore_configurations() {
    local backup_dir="$1"
    
    if [ ! -d "$backup_dir" ]; then
        error_exit "Backup directory not found: $backup_dir"
    fi
    
    log "INFO" "Starting configuration restoration from: $backup_dir"
    
    # Docker Compose files
    local compose_backup="$backup_dir/web.tar.gz"
    if [ -f "$compose_backup" ]; then
        log "INFO" "Restoring Docker Compose configuration"
        tar xzf "$compose_backup" -C "/home/tony/CascadeProjects/chaba/stacks"
    fi
    
    # Environment files
    local env_backup="$backup_dir/.env"
    if [ -f "$env_backup" ]; then
        log "INFO" "Restoring environment file"
        cp "$env_backup" "/home/tony/CascadeProjects/chaba/stacks/web/.env"
    fi
    
    # SSOT files
    local ssot_backup="$backup_dir/ssot.tar.gz"
    if [ -f "$ssot_backup" ]; then
        log "INFO" "Restoring SSOT files"
        tar xzf "$ssot_backup" -C "/home/tony/CascadeProjects/chaba/docs"
    fi
    
    log "INFO" "Configuration restoration completed"
}

# Verify restoration
verify_restoration() {
    log "INFO" "Starting restoration verification..."
    
    # Verify database
    if docker exec postgres psql -U chaba -d chaba -c "SELECT 1" > /dev/null 2>&1; then
        log "INFO" "Database verification passed"
    else
        log "ERROR" "Database verification failed"
        return 1
    fi
    
    # Verify volumes
    local volumes=("postgres_data" "redis_data" "weaviate_data")
    for volume in "${volumes[@]}"; do
        if docker volume inspect "$volume" > /dev/null 2>&1; then
            log "INFO" "Volume verification passed: $volume"
        else
            log "ERROR" "Volume verification failed: $volume"
        fi
    done
    
    log "INFO" "Restoration verification completed"
}

# Main restoration function
main() {
    local restore_type="$1"
    local backup_path="$2"
    
    log "INFO" "=========================================="
    log "INFO" "Starting Chaba restoration: $restore_type"
    log "INFO" "=========================================="
    
    case "$restore_type" in
        list)
            list_backups
            ;;
        database)
            restore_database "$backup_path"
            ;;
        volumes)
            restore_volumes "$backup_path"
            ;;
        configs)
            restore_configurations "$backup_path"
            ;;
        full)
            restore_database "$backup_path/postgres_*.sql.gz"
            restore_volumes "$backup_path"
            restore_configurations "$backup_path"
            verify_restoration
            ;;
        *)
            echo "Usage: $0 {list|database|volumes|configs|full} [backup_path]"
            echo ""
            echo "Commands:"
            echo "  list              - List available backups"
            echo "  database <file>   - Restore database from file"
            echo "  volumes <dir>     - Restore volumes from directory"
            echo "  configs <dir>     - Restore configurations from directory"
            echo "  full <dir>        - Full restoration from directory"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"