#!/bin/bash
#
# Backup Monitoring and Alerting System
# Monitors backup status and sends alerts for failures or issues
#

set -euo pipefail

# Configuration
BACKUP_ROOT="/home/tony/backups/chaba"
BACKUP_LOG="/var/log/chaba-backup.log"
MONITOR_LOG="/var/log/chaba-backup-monitor.log"
ALERT_LOG="/var/log/chaba-backup-alerts.log"

# Alert thresholds
MAX_BACKUP_AGE_HOURS=36
MIN_BACKUP_SIZE_MB=10
MAX_FAILURE_COUNT=3

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$MONITOR_LOG"
}

# Send alert
send_alert() {
    local severity="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    echo "[$timestamp] [$severity] $message" >> "$ALERT_LOG"
    
    # Log to main monitor log
    log "ALERT" "[$severity] $message"
    
    # Could integrate with notification system here
    # For now, just log the alert
    case "$severity" in
        critical)
            log "CRITICAL" "ALERT: $message"
            ;;
        warning)
            log "WARNING" "ALERT: $message"
            ;;
        info)
            log "INFO" "ALERT: $message"
            ;;
    esac
}

# Check backup freshness
check_backup_freshness() {
    log "INFO" "Checking backup freshness..."
    
    local latest_backup=$(ls -t "$BACKUP_ROOT/daily/postgres_*.sql.gz" 2>/dev/null | head -1)
    
    if [ -z "$latest_backup" ]; then
        send_alert "critical" "No database backups found"
        return 1
    fi
    
    local backup_age_hours=$(( ($(date +%s) - $(stat -c %Y "$latest_backup")) / 3600 ))
    
    if [ "$backup_age_hours" -gt "$MAX_BACKUP_AGE_HOURS" ]; then
        send_alert "critical" "Latest backup is ${backup_age_hours}h old (threshold: ${MAX_BACKUP_AGE_HOURS}h)"
        return 1
    fi
    
    log "INFO" "Backup freshness check passed (${backup_age_hours}h old)"
    return 0
}

# Check backup size
check_backup_size() {
    log "INFO" "Checking backup size..."
    
    local latest_backup=$(ls -t "$BACKUP_ROOT/daily/postgres_*.sql.gz" 2>/dev/null | head -1)
    
    if [ -z "$latest_backup" ]; then
        send_alert "critical" "No database backups found for size check"
        return 1
    fi
    
    local backup_size_mb=$(du -m "$latest_backup" | cut -f1)
    
    if [ "$backup_size_mb" -lt "$MIN_BACKUP_SIZE_MB" ]; then
        send_alert "warning" "Backup size suspiciously small: ${backup_size_mb}MB (threshold: ${MIN_BACKUP_SIZE_MB}MB)"
        return 1
    fi
    
    log "INFO" "Backup size check passed (${backup_size_mb}MB)"
    return 0
}

# Check backup integrity
check_backup_integrity() {
    log "INFO" "Checking backup integrity..."
    
    local latest_backup=$(ls -t "$BACKUP_ROOT/daily/postgres_*.sql.gz" 2>/dev/null | head -1)
    
    if [ -z "$latest_backup" ]; then
        send_alert "critical" "No database backups found for integrity check"
        return 1
    fi
    
    if gzip -t "$latest_backup" 2>/dev/null; then
        log "INFO" "Backup integrity check passed"
        return 0
    else
        send_alert "critical" "Backup integrity check failed: $latest_backup"
        return 1
    fi
}

# Check backup completeness
check_backup_completeness() {
    log "INFO" "Checking backup completeness..."
    
    local required_backups=("postgres" "volumes" "configs" "docs")
    local missing_backups=()
    
    for backup_type in "${required_backups[@]}"; do
        local backup_count=$(ls -1 "$BACKUP_ROOT/daily/${backup_type}_*.tar.gz" 2>/dev/null | wc -l)
        
        if [ "$backup_count" -eq 0 ]; then
            missing_backups+=("$backup_type")
        fi
    done
    
    if [ ${#missing_backups[@]} -gt 0 ]; then
        send_alert "warning" "Missing backup types: ${missing_backups[*]}"
        return 1
    fi
    
    log "INFO" "Backup completeness check passed"
    return 0
}

# Check backup rotation
check_backup_rotation() {
    log "INFO" "Checking backup rotation..."
    
    local daily_count=$(ls -1 "$BACKUP_ROOT/daily/"*.{sql.gz,tar.gz} 2>/dev/null | wc -l)
    local weekly_count=$(ls -1 "$BACKUP_ROOT/weekly/"* 2>/dev/null | wc -l)
    local monthly_count=$(ls -1 "$BACKUP_ROOT/monthly/"* 2>/dev/null | wc -l)
    
    log "INFO" "Backup counts: daily=$daily_count, weekly=$weekly_count, monthly=$monthly_count"
    
    # Check if rotation is working (should not have excessive old backups)
    local old_daily_count=$(find "$BACKUP_ROOT/daily" -name "*.sql.gz" -mtime +35 2>/dev/null | wc -l)
    if [ "$old_daily_count" -gt 0 ]; then
        send_alert "warning" "Found $old_daily_count daily backups older than 35 days (rotation may not be working)"
        return 1
    fi
    
    log "INFO" "Backup rotation check passed"
    return 0
}

# Check backup failures
check_backup_failures() {
    log "INFO" "Checking recent backup failures..."
    
    local failure_count=$(grep -c "ERROR.*backup failed" "$BACKUP_LOG" 2>/dev/null || echo "0")
    
    if [ "$failure_count" -gt "$MAX_FAILURE_COUNT" ]; then
        send_alert "critical" "Found $failure_count backup failures in log (threshold: $MAX_FAILURE_COUNT)"
        return 1
    fi
    
    log "INFO" "Backup failure check passed ($failure_count failures)"
    return 0
}

# Check disk space
check_disk_space() {
    log "INFO" "Checking disk space..."
    
    local available_gb=$(df -BG "$BACKUP_ROOT" | awk 'NR==2 {print $4}' | sed 's/G//')
    local used_percent=$(df -BG "$BACKUP_ROOT" | awk 'NR==2 {print $5}' | sed 's/%//')
    
    log "INFO" "Disk space: ${available_gb}GB available, ${used_percent}% used"
    
    if [ "$available_gb" -lt 5 ]; then
        send_alert "critical" "Low disk space: ${available_gb}GB available"
        return 1
    fi
    
    if [ "$used_percent" -gt 90 ]; then
        send_alert "warning" "High disk usage: ${used_percent}% used"
        return 1
    fi
    
    log "INFO" "Disk space check passed"
    return 0
}

# Generate monitoring report
generate_monitoring_report() {
    log "INFO" "Generating monitoring report..."
    
    local report_file="$BACKUP_ROOT/logs/monitoring_report_$(date +%Y%m%d_%H%M%S).txt"
    
    cat > "$report_file" << EOF
Chaba Backup Monitoring Report
===============================
Date: $(date)

Backup Status:
--------------
EOF
    
    # Backup freshness
    local latest_backup=$(ls -t "$BACKUP_ROOT/daily/postgres_*.sql.gz" 2>/dev/null | head -1)
    if [ -n "$latest_backup" ]; then
        local backup_age_hours=$(( ($(date +%s) - $(stat -c %Y "$latest_backup")) / 3600 ))
        echo "Latest backup: $backup_age_hours hours old" >> "$report_file"
    else
        echo "Latest backup: NOT FOUND" >> "$report_file"
    fi
    
    # Backup counts
    local daily_count=$(ls -1 "$BACKUP_ROOT/daily/"*.{sql.gz,tar.gz} 2>/dev/null | wc -l)
    local weekly_count=$(ls -1 "$BACKUP_ROOT/weekly/"* 2>/dev/null | wc -l)
    local monthly_count=$(ls -1 "$BACKUP_ROOT/monthly/"* 2>/dev/null | wc -l)
    
    cat >> "$report_file" << EOF
Daily backups: $daily_count
Weekly backups: $weekly_count
Monthly backups: $monthly_count

Storage Usage:
--------------
EOF
    
    local total_size=$(du -sh "$BACKUP_ROOT" | cut -f1)
    local available_gb=$(df -BG "$BACKUP_ROOT" | awk 'NR==2 {print $4}' | sed 's/G//')
    local used_percent=$(df -BG "$BACKUP_ROOT" | awk 'NR==2 {print $5}' | sed 's/%//')
    
    cat >> "$report_file" << EOF
Total backup size: $total_size
Available disk space: ${available_gb}GB
Disk usage: ${used_percent}%

Recent Alerts:
--------------
EOF
    
    # Recent alerts
    tail -10 "$ALERT_LOG" >> "$report_file" 2>/dev/null || echo "No recent alerts" >> "$report_file"
    
    log "INFO" "Monitoring report generated: $report_file"
}

# Main monitoring function
main() {
    local check_type="${1:-all}"
    
    log "INFO" "=========================================="
    log "INFO" "Starting backup monitoring: $check_type"
    log "INFO" "=========================================="
    
    local checks_passed=0
    local checks_failed=0
    
    case "$check_type" in
        freshness)
            check_backup_freshness && ((checks_passed++)) || ((checks_failed++))
            ;;
        size)
            check_backup_size && ((checks_passed++)) || ((checks_failed++))
            ;;
        integrity)
            check_backup_integrity && ((checks_passed++)) || ((checks_failed++))
            ;;
        completeness)
            check_backup_completeness && ((checks_passed++)) || ((checks_failed++))
            ;;
        rotation)
            check_backup_rotation && ((checks_passed++)) || ((checks_failed++))
            ;;
        failures)
            check_backup_failures && ((checks_passed++)) || ((checks_failed++))
            ;;
        disk)
            check_disk_space && ((checks_passed++)) || ((checks_failed++))
            ;;
        all)
            check_backup_freshness && ((checks_passed++)) || ((checks_failed++))
            check_backup_size && ((checks_passed++)) || ((checks_failed++))
            check_backup_integrity && ((checks_passed++)) || ((checks_failed++))
            check_backup_completeness && ((checks_passed++)) || ((checks_failed++))
            check_backup_rotation && ((checks_passed++)) || ((checks_failed++))
            check_backup_failures && ((checks_passed++)) || ((checks_failed++))
            check_disk_space && ((checks_passed++)) || ((checks_failed++))
            generate_monitoring_report
            ;;
        *)
            echo "Usage: $0 {freshness|size|integrity|completeness|rotation|failures|disk|all}"
            exit 1
            ;;
    esac
    
    log "INFO" "Monitoring completed: $checks_passed passed, $checks_failed failed"
    
    if [ "$checks_failed" -gt 0 ]; then
        exit 1
    fi
}

# Run main function
main "$@"