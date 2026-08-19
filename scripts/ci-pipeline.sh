#!/bin/bash
#
# CI/CD Pipeline Script for Chaba Infrastructure
# Provides automated testing, validation, and deployment pipeline
#

set -eo pipefail

# Configuration
PROJECT_ROOT="/home/tony/CascadeProjects/chaba"
CI_LOG="/home/tony/CascadeProjects/chaba/logs/ci-pipeline.log"
TEST_RESULTS_DIR="/home/tony/CascadeProjects/chaba/tests/results"

# Create directories
mkdir -p "$(dirname "$CI_LOG")"
mkdir -p "$TEST_RESULTS_DIR"

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$CI_LOG"
}

# Error handling
error_exit() {
    log "ERROR" "$1"
    exit 1
}

# Test stage
test_stage() {
    local stage_name="$1"
    
    log "INFO" "=========================================="
    log "INFO" "Running Stage: $stage_name"
    log "INFO" "=========================================="
    
    local stage_start=$(date +%s)
    
    case "$stage_name" in
        syntax)
            log "INFO" "Testing syntax of all scripts..."
            local script_count=$(find "$PROJECT_ROOT/scripts" -maxdepth 1 -name "*.sh" -type f 2>/dev/null | wc -l)
            log "INFO" "Found $script_count shell scripts to check"
            find "$PROJECT_ROOT/scripts" -maxdepth 1 -name "*.sh" -type f 2>/dev/null | while read script; do
                bash -n "$script" 2>/dev/null || error_exit "Shell script syntax check failed: $script"
            done
            local mjs_count=$(find "$PROJECT_ROOT/scripts" -maxdepth 1 -name "*.mjs" -type f 2>/dev/null | wc -l)
            log "INFO" "Found $mjs_count Node.js scripts to check"
            find "$PROJECT_ROOT/scripts" -maxdepth 1 -name "*.mjs" -type f 2>/dev/null | while read script; do
                node -c "$script" 2>/dev/null || error_exit "Node.js script syntax check failed: $script"
            done
            log "INFO" "Syntax check passed"
            ;;
        
        validation)
            log "INFO" "Running validation tests..."
            if [ -f "$PROJECT_ROOT/scripts/ssot-validate-sync.sh" ]; then
                "$PROJECT_ROOT/scripts/ssot-validate-sync.sh" 2>/dev/null || error_exit "SSOT validation failed"
            fi
            log "INFO" "Validation tests passed"
            ;;
        
        backup)
            log "INFO" "Testing backup system..."
            if [ -f "$PROJECT_ROOT/scripts/test-backup.sh" ]; then
                "$PROJECT_ROOT/scripts/test-backup.sh" 2>/dev/null || error_exit "Backup system test failed"
            fi
            log "INFO" "Backup system tests passed"
            ;;
        
        monitoring)
            log "INFO" "Testing monitoring dashboard..."
            if [ -f "$PROJECT_ROOT/scripts/test-monitoring-dashboard.sh" ]; then
                "$PROJECT_ROOT/scripts/test-monitoring-dashboard.sh" 2>/dev/null || error_exit "Monitoring dashboard test failed"
            fi
            log "INFO" "Monitoring dashboard tests passed"
            ;;
        
        security)
            log "INFO" "Running security audit..."
            if [ -f "$PROJECT_ROOT/scripts/security-audit.sh" ]; then
                "$PROJECT_ROOT/scripts/security-audit.sh" 2>/dev/null || error_exit "Security audit failed"
            fi
            log "INFO" "Security audit completed"
            ;;
        
        services)
            log "INFO" "Testing service health..."
            cd "$PROJECT_ROOT/stacks/web"
            
            # Check if services are running
            local critical_services=("caddy" "postgres" "redis")
            for service in "${critical_services[@]}"; do
                if docker ps | grep -q "$service"; then
                    log "INFO" "Service $service is running"
                else
                    log "WARN" "Service $service is not running"
                fi
            done
            
            # Test web service
            if curl -f -s http://localhost:8080/ > /dev/null 2>&1; then
                log "INFO" "Web service is accessible"
            else
                log "WARN" "Web service not accessible"
            fi
            
            cd "$PROJECT_ROOT"
            log "INFO" "Service health tests completed"
            ;;
        
        audits)
            log "INFO" "Running audit suite..."
            if [ -f "$PROJECT_ROOT/scripts/audits/run.mjs" ]; then
                node "$PROJECT_ROOT/scripts/audits/run.mjs" || error_exit "Audit suite failed"
            fi
            log "INFO" "Audit suite completed"
            ;;
        
        all)
            test_stage syntax
            test_stage validation
            test_stage audits
            test_stage backup
            test_stage monitoring
            test_stage security
            test_stage services
            ;;
        
        *)
            error_exit "Unknown test stage: $stage_name"
            ;;
    esac
    
    local stage_end=$(date +%s)
    local stage_duration=$((stage_end - stage_start))
    log "INFO" "Stage $stage_name completed in ${stage_duration}s"
}

# Generate test report
generate_test_report() {
    log "INFO" "Generating test report..."
    
    local report_file="$PROJECT_ROOT/reports/ci-test-report-$(date +%Y%m%d_%H%M%S).txt"
    
    cat > "$report_file" << EOF
Chaba CI/CD Pipeline Test Report
================================
Date: $(date)
Pipeline: Automated Testing and Validation

Test Stages:
-------------
EOF
    
    # Add test results from log
    grep "Running Stage:" "$CI_LOG" >> "$report_file" 2>/dev/null || echo "No test stages found" >> "$report_file"
    
    cat >> "$report_file" << EOF

Test Results:
-------------
EOF
    
    # Add completion status
    grep "completed in" "$CI_LOG" >> "$report_file" 2>/dev/null || echo "No completion status found" >> "$report_file"
    
    cat >> "$report_file" << EOF

Next Steps:
-----------
- Review test results
- Fix any failed tests
- Re-run pipeline if needed
- Proceed to deployment if all tests pass

Deployment:
-----------
To deploy after successful tests:
  $PROJECT_ROOT/scripts/deploy.sh deploy

Rollback:
-----------
To rollback if deployment fails:
  $PROJECT_ROOT/scripts/deploy.sh rollback

EOF
    
    log "INFO" "Test report generated: $report_file"
}

# Main CI/CD function
main() {
    local test_stage="${1:-all}"
    
    log "INFO" "=========================================="
    log "INFO" "Starting Chaba CI/CD Pipeline"
    log "INFO" "=========================================="
    
    local pipeline_start=$(date +%s)
    
    # Run test stage
    test_stage "$test_stage"
    
    # Generate report
    generate_test_report
    
    local pipeline_end=$(date +%s)
    local pipeline_duration=$((pipeline_end - pipeline_start))
    
    log "INFO" "=========================================="
    log "INFO" "CI/CD Pipeline Completed"
    log "INFO" "=========================================="
    log "INFO" "Pipeline duration: ${pipeline_duration}s"
    log "INFO" "Test report generated"
    
    exit 0
}

# Run main function
main "$@"