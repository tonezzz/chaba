#!/bin/bash
# Test script for validating global rules effectiveness and MDDB search performance

echo "=== Testing Global Rules and MDDB Search Effectiveness ==="
echo "Test Date: $(date)"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
PASSED=0
FAILED=0

# Function to check test result
check_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ PASSED${NC}: $2"
        ((PASSED++))
    else
        echo -e "${RED}❌ FAILED${NC}: $2"
        ((FAILED++))
    fi
}

# Test 1: MDDB Health Check
echo "Test 1: MDDB Health Check"
HEALTH_STATUS=$(curl -s http://tony-omen.local:11023/health | jq -r '.status')
if [ "$HEALTH_STATUS" = "healthy" ]; then
    check_result 0 "MDDB health check - status: $HEALTH_STATUS"
else
    check_result 1 "MDDB health check - status: $HEALTH_STATUS"
fi
echo ""

# Test 2: MDDB Search Quality
echo "Test 2: MDDB Search Quality (GPU memory management)"
SEARCH_RESULT=$(curl -s -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"GPU memory management","limit":3,"collection":"kb-system"}')
TOP_SCORE=$(echo $SEARCH_RESULT | jq -r '.results[0].score')
SCORE_FLOAT=$(echo "$TOP_SCORE" | awk '{printf "%.2f", $1}')
SCORE_COMPARE=$(echo "$SCORE_FLOAT > 0.45" | bc -l)
if [ "$SCORE_COMPARE" -eq 1 ]; then
    check_result 0 "MDDB search quality - top score: $SCORE_FLOAT (> 0.45)"
else
    check_result 1 "MDDB search quality - top score: $SCORE_FLOAT (not > 0.45)"
fi
echo ""

# Test 3: MDDB Search Performance
echo "Test 3: MDDB Search Performance"
START_TIME=$(date +%s%N)
curl -s -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"health check","limit":5}' > /dev/null
END_TIME=$(date +%s%N)
RESPONSE_TIME=$(( (END_TIME - START_TIME) / 1000000 )) # Convert to milliseconds
if [ $RESPONSE_TIME -lt 600 ]; then
    check_result 0 "MDDB search performance - response time: ${RESPONSE_TIME}ms (< 600ms)"
else
    check_result 1 "MDDB search performance - response time: ${RESPONSE_TIME}ms (not < 600ms)"
fi
echo ""

# Test 4: Collection Coverage
echo "Test 4: Collection Coverage"
COLLECTION_COUNT=$(curl -s http://tony-omen.local:11023/v1/vector-stats | jq '.collections | length')
if [ "$COLLECTION_COUNT" -ge 13 ]; then
    check_result 0 "Collection coverage - $COLLECTION_COUNT collections (>= 13)"
else
    check_result 1 "Collection coverage - $COLLECTION_COUNT collections (not >= 13)"
fi
echo ""

# Test 5: Document Coverage
echo "Test 5: Document Coverage"
TOTAL_DOCS=$(curl -s http://tony-omen.local:11023/v1/stats | jq '.totalDocuments')
if [ "$TOTAL_DOCS" -gt 150 ]; then
    check_result 0 "Document coverage - $TOTAL_DOCS documents (> 150)"
else
    check_result 1 "Document coverage - $TOTAL_DOCS documents (not > 150)"
fi
echo ""

# Test 6: SSOT Auto-Sync Service
echo "Test 6: SSOT Auto-Sync Service Status"
SYNC_STATUS=$(systemctl is-active ssot-sync.service 2>/dev/null || echo "unknown")
if [ "$SYNC_STATUS" = "active" ]; then
    check_result 0 "SSOT auto-sync service - status: $SYNC_STATUS"
else
    check_result 1 "SSOT auto-sync service - status: $SYNC_STATUS"
fi
echo ""

# Test 7: SSOT Collection Documents
echo "Test 7: SSOT Collection Documents"
SSOT_DOCS=$(curl -s http://tony-omen.local:11023/v1/vector-stats | jq '.collections["ssot-infrastructure"].total_documents')
if [ "$SSOT_DOCS" -eq 10 ]; then
    check_result 0 "SSOT infrastructure collection - $SSOT_DOCS documents (expected 10)"
else
    check_result 1 "SSOT infrastructure collection - $SSOT_DOCS documents (expected 10)"
fi
echo ""

# Test 8: KB Collection Documents
echo "Test 8: KB System Collection Documents"
KB_DOCS=$(curl -s http://tony-omen.local:11023/v1/vector-stats | jq '.collections["kb-system"].total_documents')
if [ "$KB_DOCS" -ge 25 ]; then
    check_result 0 "KB system collection - $KB_DOCS documents (>= 25)"
else
    check_result 1 "KB system collection - $KB_DOCS documents (not >= 25)"
fi
echo ""

# Test 9: Cross-Collection Search
echo "Test 9: Cross-Collection Search (within kb-system)"
CROSS_RESULT=$(curl -s -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"health check configuration","limit":10,"collection":"kb-system"}')
CROSS_COUNT=$(echo $CROSS_RESULT | jq '.results | length')
if [ "$CROSS_COUNT" -ge 1 ]; then
    check_result 0 "Cross-collection search - $CROSS_COUNT results (>= 1)"
else
    check_result 1 "Cross-collection search - $CROSS_COUNT results (not >= 1)"
fi
echo ""

# Test 10: MDDB Container Status
echo "Test 10: MDDB Container Status"
CONTAINER_STATUS=$(docker ps --format '{{.Status}}' --filter name=mddb | head -1)
if [[ $CONTAINER_STATUS == *"Up"* ]]; then
    check_result 0 "MDDB container status - $CONTAINER_STATUS"
else
    check_result 1 "MDDB container status - $CONTAINER_STATUS"
fi
echo ""

# Test 11: Ollama Embedding Service
echo "Test 11: Ollama Embedding Service Status"
OLLAMA_STATUS=$(docker ps --format '{{.Status}}' --filter name=ollama | head -1)
if [[ $OLLAMA_STATUS == *"Up"* ]]; then
    check_result 0 "Ollama container status - $OLLAMA_STATUS"
else
    check_result 1 "Ollama container status - $OLLAMA_STATUS"
fi
echo ""

# Test 12: MCP Health Service
echo "Test 12: MCP Health Service (via mcp-health)"
# This would typically be tested via MCP tools, but we can check if the service is configured
if [ -f "/home/tony/.config/devin/mcp_config.json" ]; then
    MCP_HEALTH_CONFIG=$(grep -A 5 "mcp-health" /home/tony/.config/devin/mcp_config.json | grep -q "HEALTH_CONFIG")
    if [ $? -eq 0 ]; then
        check_result 0 "MCP health service configured"
    else
        check_result 1 "MCP health service not properly configured"
    fi
else
    check_result 1 "MCP config file not found"
fi
echo ""

# Summary
echo "=== Test Summary ==="
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"
echo "Total: $((PASSED + FAILED))"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed. Please review the results above.${NC}"
    exit 1
fi