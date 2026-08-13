#!/bin/bash
#
# Security Hardening Script for Chaba Infrastructure
# Implements security fixes based on audit findings
#

set -eo pipefail

# Configuration
SECURITY_LOG="/home/tony/CascadeProjects/chaba/logs/security-harden.log"
PROJECT_ROOT="/home/tony/CascadeProjects/chaba"

# Create directories
mkdir -p "$(dirname "$SECURITY_LOG")"

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$SECURITY_LOG"
}

# Fix file permissions
fix_file_permissions() {
    log "INFO" "Fixing file permissions..."
    
    # Fix environment files
    local env_files=(
        "$PROJECT_ROOT/.env"
        "$PROJECT_ROOT/stacks/web/.env"
        "$PROJECT_ROOT/stacks/web/.env.production"
    )
    
    for env_file in "${env_files[@]}"; do
        if [ -f "$env_file" ]; then
            chmod 600 "$env_file"
            log "INFO" "Fixed permissions: $env_file (600)"
        fi
    done
    
    # Fix backup log permissions
    local backup_logs=("/var/log/chaba-backup.log" "/var/log/chaba-backup-monitor.log")
    for log_file in "${backup_logs[@]}"; do
        if [ -f "$log_file" ]; then
            chmod 640 "$log_file"
            log "INFO" "Fixed permissions: $log_file (640)"
        fi
    done
}

# Add User directive to systemd services
fix_systemd_services() {
    log "INFO" "Adding User directive to systemd services..."
    
    local systemd_dir="$PROJECT_ROOT/systemd"
    if [ -d "$systemd_dir" ]; then
        for service_file in "$systemd_dir"/*.service; do
            if [ -f "$service_file" ]; then
                if ! grep -q "User=" "$service_file"; then
                    # Add User=tony after [Service] section
                    sed -i '/\[Service\]/a User=tony' "$service_file"
                    log "INFO" "Added User directive to: $(basename "$service_file")"
                fi
            fi
        done
    fi
}

# Generate security hardening recommendations
generate_recommendations() {
    log "INFO" "Generating security hardening recommendations..."
    
    cat > "$PROJECT_ROOT/reports/security-recommendations-$(date +%Y%m%d).txt" << EOF
Chaba Security Hardening Recommendations
=======================================
Date: $(date)

Critical Issues (Immediate Action Required):
-------------------------------------------
1. PostgreSQL Authentication
   Issue: PostgreSQL using 'trust' authentication
   Impact: No password required for database access
   Fix: Update pg_hba.conf to use md5 or scram-sha-256 authentication
   Priority: CRITICAL
   Action Required: Manual database configuration update

Medium Risk Issues (Plan within 1 week):
-----------------------------------------
2. Docker Containers Running as Root
   Issue: Multiple containers running as root user
   Impact: Container compromise could lead to host compromise
   Fix: Add USER directive to Dockerfiles and run as non-root user
   Affected Containers: raceman-php, yomi-api, redis, status-api, etc.
   Priority: MEDIUM
   Action Required: Dockerfile updates and container rebuilds

3. Network Services on All Interfaces
   Issue: Services listening on 0.0.0.0 (all interfaces)
   Impact: Increased attack surface
   Fix: Bind services to specific interfaces when possible
   Priority: MEDIUM
   Action Required: Service configuration updates

4. PostgreSQL Network Binding
   Issue: PostgreSQL listening on all interfaces
   Impact: Database accessible from any network
   Fix: Configure listen_addresses to specific IP in postgresql.conf
   Priority: MEDIUM
   Action Required: Database configuration update

Low Risk Issues (Next maintenance window):
-------------------------------------------
5. Backup Log Permissions
   Issue: Backup logs have permissive permissions
   Impact: Log files could be read by unauthorized users
   Fix: chmod 640 on backup log files
   Priority: LOW
   Status: Auto-fixed by security-harden.sh

6. Systemd Service User Directives
   Issue: Some systemd services may run as root
   Impact: Service compromise could lead to privilege escalation
   Fix: Add User= directive to service files
   Priority: LOW
   Status: Auto-fixed by security-harden.sh

Security Best Practices:
-----------------------
1. Regular Security Audits: Run security-audit.sh weekly
2. Credential Management: Use environment variables for all secrets
3. Network Segmentation: Use firewall rules to restrict access
4. Container Security: Run containers as non-root users
5. Database Security: Use strong authentication and encryption
6. Backup Security: Ensure backup storage is encrypted and access-controlled
7. Monitoring: Implement security monitoring and alerting
8. Updates: Keep all dependencies and containers updated

Next Steps:
-----------
1. Address PostgreSQL authentication (CRITICAL)
2. Plan Docker container hardening (MEDIUM)
3. Review network service bindings (MEDIUM)
4. Schedule regular security audits (ONGOING)
5. Implement security monitoring (ONGOING)

Resources:
----------
- Security Audit: scripts/security-audit.sh
- Security Hardening: scripts/security-harden.sh
- PostgreSQL Security: https://www.postgresql.org/docs/current/security.html
- Docker Security: https://docs.docker.com/engine/security/
- Systemd Security: https://www.freedesktop.org/software/systemd/man/systemd.exec.html
EOF
    
    log "INFO" "Security recommendations generated"
}

# Main hardening function
main() {
    log "INFO" "=========================================="
    log "INFO" "Starting Chaba Security Hardening"
    log "INFO" "=========================================="
    
    # Apply fixes
    fix_file_permissions
    fix_systemd_services
    
    # Generate recommendations
    generate_recommendations
    
    # Summary
    log "INFO" "=========================================="
    log "INFO" "Security Hardening Completed"
    log "INFO" "=========================================="
    log "INFO" "Auto-fixed: File permissions, systemd services"
    log "INFO" "Manual fixes required: PostgreSQL authentication, Docker security"
    log "INFO" "See recommendations report for detailed action items"
    
    exit 0
}

# Run main function
main "$@"