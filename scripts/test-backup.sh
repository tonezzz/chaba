#!/bin/bash
#
# Backup System Test Script
# Tests backup functionality without affecting production data
#

# Configuration
TEST_BACKUP_ROOT="/tmp/chaba-backup-test"
TEST_LOG="/tmp/chaba-backup-test.log"

# Cleanup function
cleanup() {
    echo "Cleaning up test environment..."
    rm -rf "$TEST_BACKUP_ROOT"
    rm -f "$TEST_LOG"
}

# Set trap for cleanup
trap cleanup EXIT

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$TEST_LOG"
}

# Test backup manager
test_backup_manager() {
    log "INFO" "Testing backup manager..."
    
    # Check if script exists and is executable
    if [ ! -x "/home/tony/CascadeProjects/chaba-tony-dell/scripts/backup-manager.sh" ]; then
        log "ERROR" "backup-manager.sh not found or not executable"
        return 1
    fi
    
    log "INFO" "Backup manager test passed (script exists and executable)"
    return 0
}

# Test restore manager
test_restore_manager() {
    log "INFO" "Testing restore manager..."
    
    # Check if script exists and is executable
    if [ ! -x "/home/tony/CascadeProjects/chaba-tony-dell/scripts/restore-manager.sh" ]; then
        log "ERROR" "restore-manager.sh not found or not executable"
        return 1
    fi
    
    log "INFO" "Restore manager test passed (script exists and executable)"
    return 0
}

# Test backup monitor
test_backup_monitor() {
    log "INFO" "Testing backup monitor..."
    
    # Check if script exists and is executable
    if [ ! -x "/home/tony/CascadeProjects/chaba-tony-dell/scripts/backup-monitor.sh" ]; then
        log "ERROR" "backup-monitor.sh not found or not executable"
        return 1
    fi
    
    log "INFO" "Backup monitor test passed (script exists and executable)"
    return 0
}

# Test systemd service files
test_systemd_files() {
    log "INFO" "Testing systemd service files..."
    
    local service_dir="/home/tony/CascadeProjects/chaba-tony-dell/systemd"
    
    # Check if service files exist
    if [ ! -f "$service_dir/chaba-backup.service" ]; then
        log "ERROR" "chaba-backup.service not found"
        return 1
    fi
    
    if [ ! -f "$service_dir/chaba-backup.timer" ]; then
        log "ERROR" "chaba-backup.timer not found"
        return 1
    fi
    
    if [ ! -f "$service_dir/chaba-backup-monitor.service" ]; then
        log "ERROR" "chaba-backup-monitor.service not found"
        return 1
    fi
    
    if [ ! -f "$service_dir/chaba-backup-monitor.timer" ]; then
        log "ERROR" "chaba-backup-monitor.timer not found"
        return 1
    fi
    
    log "INFO" "Systemd files test passed (files exist)"
    return 0
}

# Test script permissions
test_permissions() {
    log "INFO" "Testing script permissions..."
    
    local scripts=(
        "/home/tony/CascadeProjects/chaba-tony-dell/scripts/backup-manager.sh"
        "/home/tony/CascadeProjects/chaba-tony-dell/scripts/restore-manager.sh"
        "/home/tony/CascadeProjects/chaba-tony-dell/scripts/backup-monitor.sh"
    )
    
    for script in "${scripts[@]}"; do
        if [ ! -x "$script" ]; then
            log "ERROR" "Script not executable: $script"
            return 1
        fi
    done
    
    log "INFO" "Script permissions test passed"
    return 0
}

# Main test function
main() {
    log "INFO" "=========================================="
    log "INFO" "Starting backup system tests"
    log "INFO" "=========================================="
    
    local tests_passed=0
    local tests_failed=0
    
    # Run tests
    test_permissions || ((tests_failed++))
    test_systemd_files || ((tests_failed++))
    test_backup_manager || ((tests_failed++))
    test_restore_manager || ((tests_failed++))
    test_backup_monitor || ((tests_failed++))
    
    tests_passed=$((5 - tests_failed))
    
    log "INFO" "=========================================="
    log "INFO" "Test results: $tests_passed passed, $tests_failed failed"
    log "INFO" "=========================================="
    
    if [ "$tests_failed" -eq 0 ]; then
        log "INFO" "All tests passed!"
        return 0
    else
        log "ERROR" "Some tests failed"
        return 1
    fi
}

# Run main function
main "$@"