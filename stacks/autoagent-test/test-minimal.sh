#!/bin/bash
# Minimal Smoke Test for AutoAgent Test Stack
# 
# This script performs fast smoke tests that don't require:
# - External API keys (uses mocks/defaults)
# - VPN connection to idc1
# - PostgreSQL database
#
# Usage: ./test-minimal.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

TESTS_PASSED=0
TESTS_FAILED=0

test_pass() {
    echo -e "${GREEN}✓${NC} $1"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

test_fail() {
    echo -e "${RED}✗${NC} $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

test_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

echo "==================================="
echo "AutoAgent Minimal Smoke Test"
echo "==================================="
echo ""

if [ ! -f "docker-compose.yml" ]; then
    echo "Error: Must run from stacks/autoagent-test directory"
    exit 1
fi

# Detect container name
CONTAINER_NAME=""
if docker ps | grep -q "autoagent-test-minimal"; then
    CONTAINER_NAME="autoagent-test-minimal"
    echo "Using minimal container ($CONTAINER_NAME)..."
elif docker ps | grep -q "autoagent-test"; then
    CONTAINER_NAME="autoagent-test"
    echo "Using full container ($CONTAINER_NAME)..."
else
    echo "[1/5] Building container..."
    docker-compose build autoagent 2>&1 | tail -5
    echo ""
    echo "[2/5] Starting container..."
    docker-compose up -d autoagent
    sleep 3
    CONTAINER_NAME="autoagent-test"
fi

echo ""
echo "[3/5] Testing container health..."
if docker ps | grep -q "$CONTAINER_NAME"; then
    test_pass "Container is running"
else
    test_fail "Container failed to start"
    exit 1
fi

# Test Python imports
echo ""
echo "[4/5] Testing Python imports..."
IMPORT_RESULT=$(docker exec $CONTAINER_NAME python -c "
import sys
results = {}
for mod in ['autoagent', 'constant', 'loop_utils', 'evaluation']:
    try:
        __import__(mod)
        results[mod] = 'OK'
    except Exception as e:
        results[mod] = f'FAIL: {e}'
for mod, status in results.items():
    print(f'{mod}: {status}')
" 2>&1)

echo "$IMPORT_RESULT" | grep "autoagent: OK" > /dev/null && test_pass "Import autoagent" || test_fail "Import autoagent"
echo "$IMPORT_RESULT" | grep "constant: OK" > /dev/null && test_pass "Import constant" || test_fail "Import constant"
echo "$IMPORT_RESULT" | grep "loop_utils: OK" > /dev/null && test_pass "Import loop_utils" || test_fail "Import loop_utils"
echo "$IMPORT_RESULT" | grep "evaluation: OK" > /dev/null && test_pass "Import evaluation" || test_fail "Import evaluation"

# Test CLI availability
echo ""
echo "[5/5] Testing CLI availability..."
if docker exec $CONTAINER_NAME bash -c "which auto > /dev/null 2>&1"; then
    test_pass "CLI 'auto' command found"
else
    test_fail "CLI 'auto' command not found"
fi

# Test control server health endpoint
echo ""
echo "Testing control server..."
HEALTH_CHECK=$(docker exec $CONTAINER_NAME curl -s http://localhost:8080/api/health 2>&1 || echo "FAIL")
if echo "$HEALTH_CHECK" | grep -q "status"; then
    test_pass "Health endpoint responds"
else
    test_warn "Health endpoint check inconclusive"
fi

# Summary
echo ""
echo "==================================="
echo "Test Summary"
echo "==================================="
echo -e "Passed: ${GREEN}${TESTS_PASSED}${NC}"
echo -e "Failed: ${RED}${TESTS_FAILED}${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All critical tests passed!${NC}"
    echo ""
    echo "Container ready for:"
    echo "  - Interactive: docker exec -it $CONTAINER_NAME bash"
    if [ "$CONTAINER_NAME" = "autoagent-test-minimal" ]; then
        echo "  - Control panel: http://localhost:8096/"
        echo "  - Health: curl http://localhost:8096/api/health"
    else
        echo "  - Control panel: http://localhost:8059/"
        echo "  - Health: curl http://localhost:8059/api/health"
    fi
    exit 0
else
    echo -e "${RED}Some tests failed. Check logs:${NC}"
    echo "  docker logs $CONTAINER_NAME"
    exit 1
fi
