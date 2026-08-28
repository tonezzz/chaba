#!/bin/bash
#
# Automated Deployment Script for Chaba Infrastructure
# Provides safe deployment with testing, validation, and rollback capabilities
#

set -eo pipefail

# Configuration
PROJECT_ROOT="/home/tony/CascadeProjects/chaba"
DEPLOYMENT_LOG="/home/tony/CascadeProjects/chaba/logs/deployment.log"
BACKUP_DIR="/home/tony/CascadeProjects/chaba/deployments/backups"
ROLLBACK_DIR="/home/tony/CascadeProjects/chaba/deployments/rollbacks"

# Create directories
mkdir -p "$(dirname "$DEPLOYMENT_LOG")"
mkdir -p "$BACKUP_DIR"
mkdir -p "$ROLLBACK_DIR"

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$DEPLOYMENT_LOG"
}

# Error handling
error_exit() {
    log "ERROR" "$1"
    log "ERROR" "Deployment failed - rolling back..."
    rollback_deployment
    exit 1
}

# Pre-deployment backup
pre_deployment_backup() {
    log "INFO" "Creating pre-deployment backup..."
    
    local backup_timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/pre-deploy_$backup_timestamp.tar.gz"
    
    # Backup critical configurations
    tar czf "$backup_file" \
        "$PROJECT_ROOT/stacks/web/docker-compose.yml" \
        "$PROJECT_ROOT/stacks/web/.env" \
        "$PROJECT_ROOT/systemd/" \
        "$PROJECT_ROOT/scripts/" \
        2>/dev/null || error_exit "Failed to create pre-deployment backup"
    
    log "INFO" "Pre-deployment backup created: $backup_file"
    echo "$backup_file"
}

# Run pre-deployment tests
run_pre_deployment_tests() {
    log "INFO" "Running pre-deployment tests..."
    
    # Test syntax of all shell scripts
    log "INFO" "Testing shell script syntax..."
    find "$PROJECT_ROOT/scripts" -name "*.sh" -exec bash -n {} \; 2>/dev/null || error_exit "Shell script syntax check failed"
    
    # Test syntax of Node.js scripts
    log "INFO" "Testing Node.js script syntax..."
    find "$PROJECT_ROOT/scripts" -name "*.mjs" -exec node -c {} \; 2>/dev/null || error_exit "Node.js script syntax check failed"
    
    # Validate SSOT files
    log "INFO" "Validating SSOT files..."
    if [ -f "$PROJECT_ROOT/scripts/ssot-validate-sync.sh" ]; then
        "$PROJECT_ROOT/scripts/ssot-validate-sync.sh" 2>/dev/null || error_exit "SSOT validation failed"
    fi
    
    # Test backup system
    log "INFO" "Testing backup system..."
    if [ -f "$PROJECT_ROOT/scripts/test-backup.sh" ]; then
        "$PROJECT_ROOT/scripts/test-backup.sh" 2>/dev/null || error_exit "Backup system test failed"
    fi
    
    # Test monitoring dashboard
    log "INFO" "Testing monitoring dashboard..."
    if [ -f "$PROJECT_ROOT/scripts/test-monitoring-dashboard.sh" ]; then
        "$PROJECT_ROOT/scripts/test-monitoring-dashboard.sh" 2>/dev/null || error_exit "Monitoring dashboard test failed"
    fi
    
    log "INFO" "All pre-deployment tests passed"
}

# Deploy services
deploy_services() {
    log "INFO" "Deploying services..."
    
    cd "$PROJECT_ROOT/stacks/web"
    
    # Pull latest images
    log "INFO" "Pulling latest Docker images..."
    docker compose pull 2>/dev/null || log "WARN" "Some images could not be pulled (may not exist)"
    
    # Restart services
    log "INFO" "Restarting services..."
    docker compose up -d 2>/dev/null || error_exit "Failed to start services"
    
    # Wait for services to be healthy
    log "INFO" "Waiting for services to be healthy..."
    sleep 10
    
    # Check service health
    local unhealthy_services=$(docker compose ps --format "{{.Service}} {{.Health}}" | grep -v "healthy" || true)
    if [ -n "$unhealthy_services" ]; then
        log "WARN" "Some services are unhealthy: $unhealthy_services"
    else
        log "INFO" "All services are healthy"
    fi
    
    cd "$PROJECT_ROOT"
}

# Post-deployment validation
post_deployment_validation() {
    log "INFO" "Running post-deployment validation..."
    
    # Check critical services
    local critical_services=("caddy" "postgres" "redis")
    for service in "${critical_services[@]}"; do
        if ! docker ps | grep -q "$service"; then
            error_exit "Critical service not running: $service"
        fi
    done
    
    # Test web service
    log "INFO" "Testing web service..."
    if curl -f -s http://localhost:8080/ > /dev/null 2>&1; then
        log "INFO" "Web service is accessible"
    else
        log "WARN" "Web service not accessible"
    fi
    
    # Test API endpoints
    log "INFO" "Testing API endpoints..."
    if curl -f -s http://localhost:8080/health > /dev/null 2>&1; then
        log "INFO" "Health endpoint is accessible"
    else
        log "WARN" "Health endpoint not accessible"
    fi
    
    log "INFO" "Post-deployment validation completed"
}

# Create deployment snapshot
create_deployment_snapshot() {
    log "INFO" "Creating deployment snapshot..."
    
    local snapshot_timestamp=$(date +%Y%m%d_%H%M%S)
    local snapshot_file="$ROLLBACK_DIR/deployment_$snapshot_timestamp.tar.gz"
    
    # Save current state
    tar czf "$snapshot_file" \
        "$PROJECT_ROOT/stacks/web/docker-compose.yml" \
        "$PROJECT_ROOT/stacks/web/.env" \
        "$PROJECT_ROOT/systemd/" \
        "$PROJECT_ROOT/scripts/" \
        2>/dev/null || log "WARN" "Failed to create deployment snapshot"
    
    log "INFO" "Deployment snapshot created: $snapshot_file"
    echo "$snapshot_file"
}

# Rollback deployment
rollback_deployment() {
    log "INFO" "Rolling back deployment..."
    
    local latest_backup=$(ls -t "$BACKUP_DIR"/pre-deploy_*.tar.gz 2>/dev/null | head -1)
    
    if [ -z "$latest_backup" ]; then
        log "ERROR" "No pre-deployment backup found for rollback"
        exit 1
    fi
    
    log "INFO" "Restoring from backup: $latest_backup"
    
    cd "$PROJECT_ROOT"
    
    # Extract backup
    tar xzf "$latest_backup" -C / 2>/dev/null || error_exit "Failed to extract backup"
    
    # Restart services with restored configuration
    cd "$PROJECT_ROOT/stacks/web"
    docker compose up -d 2>/dev/null || error_exit "Failed to restart services after rollback"
    
    log "INFO" "Rollback completed"
}

# Generate deployment report
generate_deployment_report() {
    local status="$1"
    local deployment_time="$2"
    local backup_file="$3"
    
    local report_file="$PROJECT_ROOT/reports/deployment-$(date +%Y%m%d_%H%M%S).txt"
    
    cat > "$report_file" << EOF
Chaba Infrastructure Deployment Report
===================================
Date: $(date)
Deployment Time: $deployment_time
Status: $status

Deployment Details:
------------------
Pre-deployment Backup: $backup_file
Services Deployed: All services in docker-compose.yml
Post-deployment Validation: Completed

Service Status:
---------------
EOF
    
    # Add service status
    cd "$PROJECT_ROOT/stacks/web"
    docker compose ps >> "$report_file" 2>/dev/null || echo "Service status unavailable" >> "$report_file"
    
    cat >> "$report_file" << EOF

Next Steps:
-----------
- Monitor service health for next 30 minutes
- Check logs for any errors
- Run monitoring dashboard: http://localhost:3002
- Review security audit results

Rollback Information:
---------------------
Rollback Command: $PROJECT_ROOT/scripts/deploy.sh rollback
Rollback Location: $ROLLBACK_DIR
Latest Backup: $latest_backup

EOF
    
    log "INFO" "Deployment report generated: $report_file"
}

# Main deployment function
main() {
    local action="${1:-deploy}"
    
    log "INFO" "=========================================="
    log "INFO" "Starting Chaba Deployment: $action"
    log "INFO" "=========================================="
    
    local deployment_start=$(date +%s)
    
    case "$action" in
        deploy)
            log "INFO" "Starting deployment process..."
            
            # Pre-deployment steps
            local backup_file=$(pre_deployment_backup)
            run_pre_deployment_tests
            
            # Deployment
            deploy_services
            
            # Post-deployment validation
            post_deployment_validation
            
            # Create snapshot
            create_deployment_snapshot
            
            local deployment_end=$(date +%s)
            local deployment_duration=$((deployment_end - deployment_start))
            
            generate_deployment_report "SUCCESS" "$deployment_duration seconds" "$backup_file"
            
            log "INFO" "Deployment completed successfully in ${deployment_duration}s"
            ;;
        
        rollback)
            log "INFO" "Starting rollback process..."
            rollback_deployment
            ;;
        
        test)
            log "INFO" "Running deployment tests only..."
            run_pre_deployment_tests
            log "INFO" "All tests passed"
            ;;
        
        *)
            echo "Usage: $0 {deploy|rollback|test}"
            echo ""
            echo "Commands:"
            echo "  deploy  - Full deployment with testing and validation"
            echo "  rollback - Rollback to previous deployment"
            echo "  test    - Run pre-deployment tests only"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"