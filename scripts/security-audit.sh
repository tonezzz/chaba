#!/bin/bash
#
# Security Audit and Hardening Script for Chaba Infrastructure
# Performs comprehensive security analysis and implements hardening measures
#

set -eo pipefail

# Configuration
SECURITY_LOG="/home/tony/CascadeProjects/chaba/logs/security-audit.log"
REPORT_FILE="/home/tony/CascadeProjects/chaba/reports/security-audit-$(date +%Y%m%d_%H%M%S).txt"
PROJECT_ROOT="/home/tony/CascadeProjects/chaba"

# Create directories
mkdir -p "$(dirname "$SECURITY_LOG")"
mkdir -p "$(dirname "$REPORT_FILE")"

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$SECURITY_LOG"
}

# Security issues found
SECURITY_ISSUES=()
HIGH_RISK=0
MEDIUM_RISK=0
LOW_RISK=0

# Function to report security issue
report_issue() {
    local severity="$1"
    local category="$2"
    local message="$3"
    local recommendation="$4"
    
    SECURITY_ISSUES+=("$severity|$category|$message|$recommendation")
    
    case "$severity" in
        high)
            HIGH_RISK=$((HIGH_RISK + 1))
            log "CRITICAL" "[$category] $message"
            ;;
        medium)
            MEDIUM_RISK=$((MEDIUM_RISK + 1))
            log "WARNING" "[$category] $message"
            ;;
        low)
            LOW_RISK=$((LOW_RISK + 1))
            log "INFO" "[$category] $message"
            ;;
    esac
}

# Check file permissions
check_file_permissions() {
    log "INFO" "Checking file permissions..."
    
    # Check environment files
    local env_files=(
        "$PROJECT_ROOT/.env"
        "$PROJECT_ROOT/stacks/web/.env"
        "$PROJECT_ROOT/stacks/web/.env.production"
    )
    
    for env_file in "${env_files[@]}"; do
        if [ -f "$env_file" ]; then
            local perms=$(stat -c "%a" "$env_file")
            if [ "$perms" != "600" ] && [ "$perms" != "400" ]; then
                report_issue "high" "file-permissions" "Environment file has insecure permissions: $env_file ($perms)" "chmod 600 $env_file"
            fi
        fi
    done
    
    # Check for world-readable sensitive files (exclude node_modules and venv)
    local sensitive_patterns=("*.key" "*.pem" "*.crt" "*secret*" "*credential*")
    for pattern in "${sensitive_patterns[@]}"; do
        while IFS= read -r file; do
            # Skip node_modules and venv directories (false positives)
            if [[ "$file" =~ node_modules ]] || [[ "$file" =~ venv ]]; then
                continue
            fi
            
            if [ -f "$file" ]; then
                local perms=$(stat -c "%a" "$file")
                if [[ "$perms" =~ [0-9][0-9][4-6] ]]; then
                    report_issue "high" "file-permissions" "Sensitive file is world-readable: $file ($perms)" "chmod 600 $file"
                fi
            fi
        done < <(find "$PROJECT_ROOT" -name "$pattern" -type f 2>/dev/null)
    done
}

# Check for exposed credentials in git history
check_git_credentials() {
    log "INFO" "Checking for exposed credentials in git history..."
    
    cd "$PROJECT_ROOT"
    
    # Check for common credential patterns in git history
    local credential_patterns=("password" "api_key" "secret" "token" "credential" "private_key")
    
    for pattern in "${credential_patterns[@]}"; do
        if git log --all --full-history -S "$pattern" --source -- 2>/dev/null | grep -q "$pattern"; then
            report_issue "high" "git-security" "Potential credential exposure in git history for pattern: $pattern" "Use git-filter-repo to remove sensitive data from history"
        fi
    done
    
    # Check for .env files in git history
    if git log --all --full-history -- .env 2>/dev/null | grep -q ".env"; then
        report_issue "high" "git-security" "Environment file found in git history" "Remove .env from git history and add to .gitignore"
    fi
}

# Check Docker security
check_docker_security() {
    log "INFO" "Checking Docker security..."
    
    # Check if Docker is running as root
    if docker info 2>/dev/null | grep -q "Server Version:"; then
        # Check for containers running as root
        local root_containers=$(docker ps --format "{{.Names}}" | while read container; do
            if docker inspect "$container" 2>/dev/null | grep -q '"User": ""'; then
                echo "$container"
            fi
        done)
        
        if [ -n "$root_containers" ]; then
            report_issue "medium" "docker-security" "Containers running as root: $root_containers" "Configure containers to run as non-root users"
        fi
    fi
    
    # Check for exposed Docker daemon socket
    if [ -S /var/run/docker.sock ]; then
        local docker_sock_perms=$(stat -c "%a" /var/run/docker.sock)
        if [ "$docker_sock_perms" != "660" ]; then
            report_issue "medium" "docker-security" "Docker socket has insecure permissions: $docker_sock_perms" "chmod 660 /var/run/docker.sock"
        fi
    fi
}

# Check network security
check_network_security() {
    log "INFO" "Checking network security..."
    
    # Check for open ports
    local open_ports=$(ss -tuln | awk 'NR>1 {print $5}' | cut -d: -f2 | sort -u)
    log "INFO" "Open ports: $open_ports"
    
    # Check for services listening on all interfaces
    local all_interfaces=$(ss -tuln | awk '$5 ~ /0\.0\.0\.0/ || $5 ~ /:::/ {print $5}' | sort -u)
    if [ -n "$all_interfaces" ]; then
        report_issue "medium" "network-security" "Services listening on all interfaces: $all_interfaces" "Restrict services to specific interfaces when possible"
    fi
}

# Check systemd service security
check_systemd_security() {
    log "INFO" "Checking systemd service security..."
    
    # Check for services running as root unnecessarily
    local systemd_dir="$PROJECT_ROOT/systemd"
    if [ -d "$systemd_dir" ]; then
        for service_file in "$systemd_dir"/*.service; do
            if [ -f "$service_file" ]; then
                if ! grep -q "User=" "$service_file"; then
                    local service_name=$(basename "$service_file")
                    report_issue "low" "systemd-security" "Systemd service may run as root: $service_name" "Add User= directive to service file"
                fi
            fi
        done
    fi
}

# Check backup security
check_backup_security() {
    log "INFO" "Checking backup security..."
    
    # Check Google Drive mount security
    if mount | grep -q "gdrive.*on /home/tony/GoogleDrive"; then
        local gdrive_perms=$(stat -c "%a" /home/tony/GoogleDrive 2>/dev/null || echo "unknown")
        log "INFO" "Google Drive mount permissions: $gdrive_perms"
        
        # Check if backup directory is accessible only to owner
        local backup_dir="/home/tony/GoogleDrive/Tony AI/backup/chaba"
        if [ -d "$backup_dir" ]; then
            local backup_perms=$(stat -c "%a" "$backup_dir")
            # Google Drive mount may have different permissions, focus on accessibility
            if [ "$backup_perms" = "777" ]; then
                report_issue "medium" "backup-security" "Backup directory has world-writable permissions: $backup_perms" "chmod 755 $backup_dir"
            fi
        fi
    else
        report_issue "high" "backup-security" "Google Drive not mounted - backups may be inaccessible" "Check rclone mount and remount if needed"
    fi
    
    # Check backup log permissions
    local backup_logs=("/home/tony/CascadeProjects/chaba/logs/chaba-backup.log" "/home/tony/CascadeProjects/chaba/logs/chaba-backup-monitor.log" "/var/log/chaba-backup.log" "/var/log/chaba-backup-monitor.log")
    for log_file in "${backup_logs[@]}"; do
        if [ -f "$log_file" ]; then
            local log_perms=$(stat -c "%a" "$log_file")
            if [ "$log_perms" != "600" ] && [ "$log_perms" != "640" ]; then
                report_issue "low" "backup-security" "Backup log has permissive permissions: $log_file ($log_perms)" "chmod 640 $log_file"
            fi
        fi
    done
}

# Check database security
check_database_security() {
    log "INFO" "Checking database security..."
    
    # Check PostgreSQL connection security
    if docker ps | grep -q postgres; then
        # Check if PostgreSQL is listening on all interfaces
        local postgres_binding=$(docker exec postgres psql -U chaba -d chaba -c "SHOW listen_addresses;" -t 2>/dev/null | xargs || echo "unknown")
        if [ "$postgres_binding" = "*" ]; then
            report_issue "medium" "database-security" "PostgreSQL listening on all interfaces" "Configure listen_addresses to specific IP in postgresql.conf"
        fi
        
        # Check for default passwords
        local pg_hba=$(docker exec postgres cat /var/lib/postgresql/data/pg_hba.conf 2>/dev/null || echo "")
        if echo "$pg_hba" | grep -q "trust"; then
            report_issue "high" "database-security" "PostgreSQL using 'trust' authentication" "Use md5 or scram-sha-256 authentication"
        fi
    fi
}

# Check API key security
check_api_key_security() {
    log "INFO" "Checking API key security..."
    
    # Check for hardcoded API keys in scripts
    local api_key_patterns=("API_KEY" "SECRET_KEY" "PRIVATE_KEY" "GEMINI_API_KEY" "OPENAI_API_KEY")
    
    for pattern in "${api_key_patterns[@]}"; do
        while IFS= read -r file; do
            if grep -q "$pattern=" "$file" 2>/dev/null; then
                # Check if it's a .env file (allowed) or script (not allowed)
                if [[ ! "$file" =~ \.env$ ]]; then
                    report_issue "high" "api-security" "Potential hardcoded API key in: $file" "Move credentials to environment variables"
                fi
            fi
        done < <(find "$PROJECT_ROOT/scripts" -name "*.sh" -o -name "*.mjs" 2>/dev/null)
    done
}

# Generate security report
generate_security_report() {
    log "INFO" "Generating security report..."
    
    cat > "$REPORT_FILE" << EOF
Chaba Infrastructure Security Audit Report
==========================================
Date: $(date)
Project: $PROJECT_ROOT

Executive Summary:
------------------
Total Issues Found: ${#SECURITY_ISSUES[@]}
High Risk: $HIGH_RISK
Medium Risk: $MEDIUM_RISK
Low Risk: $LOW_RISK

Detailed Findings:
-----------------
EOF
    
    local issue_num=1
    for issue in "${SECURITY_ISSUES[@]}"; do
        IFS='|' read -r severity category message recommendation <<< "$issue"
        
        cat >> "$REPORT_FILE" << EOF
$issue_num. [$severity] $category
   Issue: $message
   Recommendation: $recommendation

EOF
        ((issue_num++))
    done
    
    cat >> "$REPORT_FILE" << EOF

Security Recommendations:
-----------------------
1. Environment Files: Ensure all .env files have 600 permissions
2. Git History: Remove any committed credentials using git-filter-repo
3. Docker: Run containers as non-root users where possible
4. Network: Restrict services to specific interfaces
5. Backup: Ensure Google Drive mount is secure and accessible
6. Database: Use strong authentication methods
7. API Keys: Never hardcode credentials in scripts
8. Monitoring: Implement regular security audits

Remediation Priority:
--------------------
1. Address all HIGH risk issues immediately
2. Plan remediation for MEDIUM risk issues within 1 week
3. Address LOW risk issues during next maintenance window

Next Audit: $(date -d '+30 days' '+%Y-%m-%d')
EOF
    
    log "INFO" "Security report generated: $REPORT_FILE"
}

# Main audit function
main() {
    log "INFO" "=========================================="
    log "INFO" "Starting Chaba Security Audit"
    log "INFO" "=========================================="
    
    # Run security checks
    check_file_permissions
    check_git_credentials
    check_docker_security
    check_network_security
    check_systemd_security
    check_backup_security
    check_database_security
    check_api_key_security
    
    # Generate report
    generate_security_report
    
    # Summary
    log "INFO" "=========================================="
    log "INFO" "Security Audit Completed"
    log "INFO" "=========================================="
    log "INFO" "Total Issues: ${#SECURITY_ISSUES[@]} (High: $HIGH_RISK, Medium: $MEDIUM_RISK, Low: $LOW_RISK)"
    log "INFO" "Report: $REPORT_FILE"
    
    if [ $HIGH_RISK -gt 0 ]; then
        log "CRITICAL" "High-risk security issues found - immediate action required"
        exit 1
    elif [ $MEDIUM_RISK -gt 0 ]; then
        log "WARNING" "Medium-risk issues found - remediation recommended"
        exit 2
    else
        log "INFO" "No critical security issues found"
        exit 0
    fi
}

# Run main function
main "$@"