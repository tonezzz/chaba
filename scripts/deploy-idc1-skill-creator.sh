#!/bin/bash
# Deploy idc1-skill-creator stack via Portainer API
# Similar pattern to deploy-idc1-assistance.sh

set -e

# Configuration
STACK_NAME="idc1-skill-creator"
PORTAINER_URL="${PORTAINER_URL:-http://127.0.0.1:9000}"
PORTAINER_API_KEY="${PORTAINER_API_KEY:-}"
PORTAINER_TOKEN="${PORTAINER_TOKEN:-}"
PORTAINER_ENDPOINT_ID="${PORTAINER_ENDPOINT_ID:-2}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    if ! command -v curl &> /dev/null; then
        log_error "curl is required but not installed"
        exit 1
    fi
    
    if [ -z "$PORTAINER_API_KEY" ] && [ -z "$PORTAINER_TOKEN" ]; then
        log_error "PORTAINER_API_KEY or PORTAINER_TOKEN must be set"
        exit 1
    fi
}

# Get authentication header
get_auth_header() {
    if [ -n "$PORTAINER_TOKEN" ]; then
        echo "Authorization: Bearer $PORTAINER_TOKEN"
    else
        echo "X-API-Key: $PORTAINER_API_KEY"
    fi
}

# Get stack ID by name
get_stack_id() {
    local stack_name="$1"
    
    log_info "Looking up stack: $stack_name"
    
    response=$(curl -s -X GET "$PORTAINER_URL/api/stacks" \
        -H "$(get_auth_header)" \
        -H "Content-Type: application/json")
    
    stack_id=$(echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for stack in data:
    if stack.get('Name') == '$stack_name':
        print(stack.get('Id'))
        break
")
    
    if [ -z "$stack_id" ]; then
        log_error "Stack '$stack_name' not found in Portainer"
        return 1
    fi
    
    log_info "Found stack ID: $stack_id"
    echo "$stack_id"
}

# Get current image digests
get_container_digests() {
    local container_name="$1"
    
    digest=$(docker inspect --format='{{index .RepoDigests 0}}' "$container_name" 2>/dev/null || echo "")
    echo "$digest"
}

# Redeploy stack via Portainer API
redeploy_stack() {
    local stack_id="$1"
    
    log_info "Redeploying stack $STACK_NAME (ID: $stack_id)"
    
    # Get pre-deployment digests
    log_info "Checking current container state..."
    pre_digest=$(get_container_digests "skill-creator")
    log_info "Pre-deployment digest: ${pre_digest:-'not found'}"
    
    # Trigger redeploy with RepullImageAndRedeploy
    response=$(curl -s -X PUT "$PORTAINER_URL/api/stacks/$stack_id?endpointId=$PORTAINER_ENDPOINT_ID" \
        -H "$(get_auth_header)" \
        -H "Content-Type: application/json" \
        -d '{
            "Prune": false,
            "PullImage": true,
            "RepullImageAndRedeploy": true
        }')
    
    if echo "$response" | grep -q "error"; then
        log_error "Failed to redeploy: $response"
        return 1
    fi
    
    log_info "Redeploy triggered successfully"
    
    # Wait for deployment
    log_info "Waiting for deployment to complete..."
    sleep 10
    
    # Check container health
    for i in {1..30}; do
        if docker ps | grep -q "skill-creator"; then
            log_info "Container is running"
            break
        fi
        sleep 2
    done
    
    # Verify health endpoint
    log_info "Verifying health endpoint..."
    for i in {1..10}; do
        if curl -s http://localhost:8091/api/health > /dev/null 2>&1; then
            log_info "Health check passed"
            break
        fi
        sleep 2
    done
    
    # Get post-deployment digests
    post_digest=$(get_container_digests "skill-creator")
    log_info "Post-deployment digest: ${post_digest:-'not found'}"
    
    if [ "$pre_digest" != "$post_digest" ] && [ -n "$post_digest" ]; then
        log_info "✅ New image deployed successfully"
    else
        log_warn "Container digests unchanged or could not verify"
    fi
    
    return 0
}

# Manual deployment (direct docker compose)
manual_deploy() {
    log_info "Performing manual deployment via docker compose..."
    
    cd /home/chaba/chaba/stacks/idc1-skill-creator
    
    log_info "Stopping existing container..."
    docker compose down 2>/dev/null || true
    
    log_info "Building and starting..."
    docker compose up -d --build
    
    log_info "Waiting for startup..."
    sleep 5
    
    # Verify
    if docker ps | grep -q "skill-creator"; then
        log_info "✅ Container is running"
        
        if curl -s http://localhost:8091/api/health > /dev/null 2>&1; then
            log_info "✅ Health check passed"
            log_info "✅ Deployment successful!"
            log_info "URL: http://idc1.surf-thailand.com:8091/skills"
        else
            log_warn "Health check failed, but container is running"
        fi
    else
        log_error "Container failed to start"
        return 1
    fi
}

# Main
main() {
    log_info "Starting deployment of $STACK_NAME"
    
    check_prerequisites
    
    # Try Portainer API first, fall back to manual
    stack_id=$(get_stack_id "$STACK_NAME" 2>/dev/null || echo "")
    
    if [ -n "$stack_id" ]; then
        redeploy_stack "$stack_id"
    else
        log_warn "Portainer stack not found, using manual deployment"
        manual_deploy
    fi
}

# Run main
main "$@"
