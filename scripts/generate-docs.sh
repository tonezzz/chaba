#!/usr/bin/env bash
# Documentation Auto-Generation
# Generates documentation from code, SSOT files, and API definitions

set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
DOCS_DIR="/home/tony/CascadeProjects/chaba/docs"
SSOT_DIR="/home/tony/CascadeProjects/chaba/docs/ssot"
KB_DIR="/home/tony/CascadeProjects/chaba/docs/kb"
LOG_FILE="/home/tony/CascadeProjects/chaba/logs/doc-generation.log"
mkdir -p "$(dirname "$LOG_FILE")"

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    local level="$1" message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
    case "$level" in
        ERROR) echo -e "${RED}[ERROR]${NC} $message" ;;
        WARN)  echo -e "${YELLOW}[WARN]${NC} $message" ;;
        INFO)  echo -e "${GREEN}[INFO]${NC} $message" ;;
    esac
}

# Generate API documentation from SSOT health configuration
generate_api_docs() {
    local health_file="$SSOT_DIR/infrastructure/ssot.health.yml"
    local output_file="$DOCS_DIR/api/health-endpoints.md"
    
    if [[ ! -f "$health_file" ]]; then
        log WARN "Health configuration file not found, skipping API docs"
        return 0
    fi
    
    mkdir -p "$(dirname "$output_file")"
    
    {
        echo "# Health Check API Endpoints"
        echo ""
        echo "Auto-generated from SSOT health configuration"
        echo "Generated: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""
        echo "## Overview"
        echo ""
        echo "This document describes all health check endpoints configured in the SSOT health configuration."
        echo ""
        echo "## Endpoints"
        echo ""
        
        # Extract service information from all health SSOTs using Python
        python3 -c "
import yaml, glob
seen = set()
for path in glob.glob('$SSOT_DIR/infrastructure/ssot.health*.yml'):
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if 'services' not in data:
        continue
    for service in data['services']:
            service_id = service.get('id', 'unknown')
            if service_id in seen:
                continue
            seen.add(service_id)
            service_name = service.get('name', service_id)
            service_type = service.get('type', 'unknown')
            
            print(f'### {service_name}')
            print(f'')
            print(f'- **ID**: {service_id}')
            print(f'- **Type**: {service_type}')
            
            if service_type == 'http':
                url = service.get('url', 'N/A')
                expected_status = service.get('expected_status', 200)
                timeout = service.get('timeout', 5)
                print(f'- **URL**: \`{url}\`')
                print(f'- **Expected Status**: {expected_status}')
                print(f'- **Timeout**: {timeout}s')
            elif service_type == 'container':
                container = service.get('container', 'N/A')
                expected_state = service.get('expected_state', 'running')
                print(f'- **Container**: {container}')
                print(f'- **Expected State**: {expected_state}')
            elif service_type == 'systemd':
                systemd_service = service.get('service', 'N/A')
                expected_state = service.get('expected_state', 'active')
                print(f'- **Service**: {systemd_service}')
                print(f'- **Expected State**: {expected_state}')
            
            category = service.get('category', 'general')
            profiles = service.get('profiles', ['all'])
            print(f'- **Category**: {category}')
            print(f'- **Profiles**: {profiles}')
            print('')
" 2>/dev/null || true
        
        echo "## Testing"
        echo ""
        echo "```bash"
        echo "# Test all health endpoints"
        echo "curl -s http://tony-dell:8080/api/health | jq ."
        echo "```"
        echo ""
        echo "## Related Documentation"
        echo ""
        echo "- [SSOT Health Configuration](../ssot/infrastructure/ssot.health.yml)"
        echo "- [Health Check Dashboard](/apps/health-check/)"
        
    } > "$output_file"
    
    log INFO "Generated API documentation: $output_file"
}

# Generate service documentation from SSOT services configuration
generate_service_docs() {
    local services_file="$SSOT_DIR/infrastructure/ssot.services.yml"
    local output_file="$DOCS_DIR/services/overview.md"
    
    if [[ ! -f "$services_file" ]]; then
        log WARN "Services configuration file not found, skipping service docs"
        return 0
    fi
    
    mkdir -p "$(dirname "$output_file")"
    
    {
        echo "# Services Overview"
        echo ""
        echo "Auto-generated from SSOT services configuration"
        echo "Generated: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""
        echo "## Service Groups"
        echo ""
        
        python3 -c "
import yaml
with open('$services_file') as f:
    data = yaml.safe_load(f)
    if 'groups' in data:
        for group_name, services in data['groups'].items():
            print(f'### {group_name}')
            print('')
            print('Services:')
            for service in services:
                print(f'- \`{service}\`')
            print('')
" 2>/dev/null || true
        
        echo "## Dependencies"
        echo ""
        
        python3 -c "
import yaml
with open('$services_file') as f:
    data = yaml.safe_load(f)
    if 'dependencies' in data:
        for service, deps in data['dependencies'].items():
            print(f'### {service}')
            print('')
            print('Depends on:')
            for dep in deps:
                print(f'- \`{dep}\`')
            print('')
" 2>/dev/null || true
        
        echo "## Related Documentation"
        echo ""
        echo "- [SSOT Services Configuration](../ssot/infrastructure/ssot.services.yml)"
        echo "- [Health Check Configuration](../ssot/infrastructure/ssot.health.yml)"
        
    } > "$output_file"
    
    log INFO "Generated service documentation: $output_file"
}

# Generate KB index from existing KB entries
generate_kb_index() {
    local output_file="$KB_DIR/README.md"
    
    mkdir -p "$(dirname "$output_file")"
    
    {
        echo "# Knowledge Base Index"
        echo ""
        echo "Auto-generated index of all KB entries"
        echo "Generated: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""
        echo "## KB Entries"
        echo ""
        
        # List all markdown files in KB directory
        for file in "$KB_DIR"/*.md; do
            if [[ -f "$file" && "$(basename "$file")" != "README.md" ]]; then
                local filename=$(basename "$file")
                local title=$(head -1 "$file" | sed 's/^# //')
                echo "- [$title]($filename)"
            fi
        done
        
        echo ""
        echo "## Categories"
        echo ""
        echo "### System"
        echo "- Health monitoring"
        echo "- Performance optimization"
        echo "- Service management"
        echo ""
        echo "### Development"
        echo "- Code quality"
        echo "- Testing"
        echo "- Deployment"
        echo ""
        echo "### Operations"
        echo "- Backup and recovery"
        echo "- Monitoring"
        echo "- Security"
        echo ""
        echo "## Related Documentation"
        echo ""
        echo "- [SSOT Documentation](../ssot/)"
        echo "- [API Documentation](../api/)"
        
    } > "$output_file"
    
    log INFO "Generated KB index: $output_file"
}

# Generate architecture documentation from SSOT
generate_architecture_docs() {
    local output_file="$DOCS_DIR/architecture/overview.md"
    
    mkdir -p "$(dirname "$output_file")"
    
    {
        echo "# System Architecture Overview"
        echo ""
        echo "Auto-generated from SSOT configuration"
        echo "Generated: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""
        echo "## Components"
        echo ""
        echo "### Web Stack"
        echo "- Caddy web server"
        echo "- Static file serving"
        echo "- Reverse proxy for APIs"
        echo ""
        echo "### Data Services"
        echo "- PostgreSQL database"
        echo "- Weaviate vector database"
        echo "- Redis cache (optional)"
        echo ""
        echo "### AI/ML Services"
        echo "- Llama Router (GPU inference)"
        echo "- GPU Queue management"
        echo "- Image generation services"
        echo ""
        echo "### Monitoring"
        echo "- Health check system"
        echo "- Performance monitoring"
        echo "- Alerting system"
        echo ""
        echo "## Service Dependencies"
        echo ""
        echo "See [Services Overview](../services/overview.md) for detailed dependency information."
        echo ""
        echo "## Related Documentation"
        echo ""
        echo "- [SSOT Index](../ssot/ssot.index.yml)"
        echo "- [Infrastructure Configuration](../ssot/infrastructure/)"
        
    } > "$output_file"
    
    log INFO "Generated architecture documentation: $output_file"
}

# Main generation function
main() {
    log INFO "Starting documentation auto-generation"
    
    local errors=0
    
    generate_api_docs || ((errors++))
    generate_service_docs || ((errors++))
    generate_kb_index || ((errors++))
    generate_architecture_docs || ((errors++))
    
    if [[ $errors -eq 0 ]]; then
        log INFO "Documentation auto-generation completed successfully"
        return 0
    else
        log ERROR "Documentation auto-generation completed with $errors errors"
        return 1
    fi
}

# Run main function
main "$@"