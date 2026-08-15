---
title: Global Rules and MDDB Search Testing Guide
description: Comprehensive testing approaches for validating global rules effectiveness and MDDB search performance
tags: [testing, validation, global-rules, MDDB, search-quality, MCP]
created: 2026-08-12
updated: 2026-08-12
category: operations
related: [global_rules.md, mddb-user-guide.md, documentation-search.md]
search_keywords: [global rules testing, MDDB search testing, validation, effectiveness testing]
---

# Global Rules and MDDB Search Testing Guide

## What it is

**Abstract**: Comprehensive testing approaches for validating the effectiveness of updated global rules and MDDB search performance, including test scenarios, validation methods, and success criteria.

## Context/Background

Global rules were updated to reflect the MDDB-based architecture and comprehensive MCP service integration. This guide provides testing methods to validate that the rules are effective and that MDDB search performs as expected.

## Testing Global Rules Effectiveness

### Test 1: Search Priority Validation

**Objective**: Verify that agents follow the new search priority (MDDB first)

**Test Scenarios**:

**Scenario 1: Documentation Search Query**
```
Query: "GPU memory management"
Expected Behavior:
1. Agent uses MDDB semantic search first
2. Falls back to ssot-search only if MDDB fails
3. Uses traditional tools only after user confirmation
```

**Validation Method**:
- Monitor agent tool calls during documentation searches
- Check that `mcp_call_tool("mddb", "semantic_search", ...)` is called first
- Verify fallback behavior is documented and confirmed with user
- No silent fallback to grep/read without explanation

**Success Criteria**:
- ✅ MDDB semantic search called first in 95%+ of documentation queries
- ✅ Fallback behavior documented and user confirmation obtained
- ✅ No silent fallback to traditional tools

**Scenario 2: SSOT-Specific Query**
```
Query: "ssot.health.yml GPU configuration"
Expected Behavior:
1. Agent uses ssot-search for exact YAML pattern matching
2. Agent does not use MDDB for exact YAML structure queries
```

**Validation Method**:
- Monitor for ssot-search skill invocation
- Verify that YAML-specific queries use ssot-search
- Check that MDDB is not used for exact YAML path queries

**Success Criteria**:
- ✅ ssot-search used for YAML-specific queries
- ✅ MDDB not used for exact YAML structure queries
- ✅ Appropriate tool selection based on query type

### Test 2: MCP Service Selection Validation

**Objective**: Verify that agents select appropriate MCP services

**Test Scenarios**:

**Scenario 1: Documentation Query**
```
Query: "How does the health check system work?"
Expected Behavior:
1. Agent uses MDDB semantic search
2. Agent does not use obsolete docs MCP server
3. Agent leverages mddb collection filtering if appropriate
```

**Validation Method**:
- Monitor for mddb semantic_search calls
- Check for absence of docs MCP server calls
- Verify collection filtering usage (kb-system, ssot-infrastructure, etc.)

**Success Criteria**:
- ✅ MDDB used for documentation queries
- ✅ No obsolete docs MCP server calls
- ✅ Appropriate collection filtering applied

**Scenario 2: System Health Query**
```
Query: "Check the health of all services"
Expected Behavior:
1. Agent uses mcp-health for comprehensive health checks
2. Agent does not use individual service checks
3. Agent leverages dependency analysis if needed
```

**Validation Method**:
- Monitor for mcp-health tool calls
- Check for check_health or get_health_status calls
- Verify dependency analysis usage

**Success Criteria**:
- ✅ mcp-health used for system health queries
- ✅ Comprehensive health checks performed
- ✅ Dependency analysis leveraged when appropriate

**Scenario 3: GPU Operations Query**
```
Query: "What is the current GPU queue status?"
Expected Behavior:
1. Agent uses mcp-gpu for GPU-specific operations
2. Agent does not use generic system monitoring
3. Agent leverages GPU queue management tools
```

**Validation Method**:
- Monitor for mcp-gpu tool calls
- Check for GPU-specific tool usage
- Verify queue status monitoring

**Success Criteria**:
- ✅ mcp-gpu used for GPU-specific queries
- ✅ Appropriate GPU tools selected
- ✅ Queue management operations correct

### Test 3: Service Failure Detection Validation

**Objective**: Verify that service failure detection works correctly

**Test Scenarios**:

**Scenario 1: MDDB Service Failure**
```
Condition: MDDB container stopped
Expected Behavior:
1. Agent detects MDDB unavailability
2. Agent proposes specific fix (restart container)
3. Agent requests user confirmation before fallback
4. Agent does not silently fall back to traditional tools
```

**Validation Method**:
- Stop MDDB container: `docker stop mddb`
- Trigger documentation search query
- Monitor agent response and tool calls
- Verify user notification and confirmation request
- Restart MDDB: `docker start mddb`

**Success Criteria**:
- ✅ MDDB failure detected and reported
- ✅ Specific fix proposed (restart container)
- ✅ User confirmation requested before fallback
- ✅ No silent fallback to traditional tools

**Scenario 2: API Key Failure**
```
Condition: Invalid API key for external service
Expected Behavior:
1. Agent detects authentication failure
2. Agent reports specific error (401/403)
3. Agent proposes fallback action
4. Agent requests user confirmation
```

**Validation Method**:
- Temporarily invalidate an API key
- Trigger service usage
- Monitor agent response
- Verify error reporting and user confirmation
- Restore API key

**Success Criteria**:
- ✅ Authentication failure detected
- ✅ Specific error reported
- ✅ Fallback action proposed
- ✅ User confirmation requested

## Testing MDDB Search Effectiveness

### Test 1: Search Quality Validation

**Objective**: Verify that MDDB semantic search provides high-quality results

**Test Scenarios**:

**Scenario 1: Semantic Understanding**
```
Query: "GPU memory management"
Expected Results:
- High relevance scores (0.45-0.80)
- Results related to GPU memory, not just "GPU" or "memory"
- Context-aware results (GPU queue, embedding service, health checks)
```

**Validation Method**:
```bash
curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"GPU memory management","limit":5,"collection":"kb-system"}'
```

**Success Criteria**:
- ✅ Relevance scores > 0.45 for top 3 results
- ✅ Results semantically related to query
- ✅ Context-aware document ranking

**Scenario 2: Cross-Collection Search**
```
Query: "health check configuration"
Expected Results:
- Results from multiple collections (kb-system, ssot-infrastructure, chaba-general)
- Relevant configuration documents across different sources
- Proper collection metadata in results
```

**Validation Method**:
```bash
curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"health check configuration","limit":10}'
```

**Success Criteria**:
- ✅ Results from multiple collections
- ✅ Relevant configuration documents
- ✅ Proper collection metadata

**Scenario 3: SSOT-Specific Search**
```
Query: "mcp infrastructure configuration"
Expected Results:
- Results from ssot-infrastructure collection
- High relevance for SSOT configuration files
- Proper SSOT metadata (source: ssot, original_path)
```

**Validation Method**:
```bash
curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"mcp infrastructure configuration","limit":5,"collection":"ssot-infrastructure"}'
```

**Success Criteria**:
- ✅ Results from ssot-infrastructure collection
- ✅ High relevance scores (> 0.50)
- ✅ Proper SSOT metadata present

### Test 2: Search Performance Validation

**Objective**: Verify that MDDB search performance meets expectations

**Test Scenarios**:

**Scenario 1: Response Time**
```
Query: Various documentation queries
Expected Performance:
- Response times: 88-550ms
- Consistent performance across queries
- No significant performance degradation
```

**Validation Method**:
```bash
# Test multiple queries and measure response times
for query in "GPU memory" "health check" "SSOT configuration" "API integration"; do
  time curl -X POST http://tony-omen.local:11023/v1/vector-search \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"$query\",\"limit\":5}"
done
```

**Success Criteria**:
- ✅ Response times < 600ms for 95% of queries
- ✅ Consistent performance (no >2x variance)
- ✅ No performance degradation over time

**Scenario 2: Concurrent Search Load**
```
Condition: Multiple simultaneous search requests
Expected Performance:
- No significant performance degradation
- Consistent response times under load
- No search failures or timeouts
```

**Validation Method**:
```bash
# Run concurrent searches
for i in {1..10}; do
  curl -X POST http://tony-omen.local:11023/v1/vector-search \
    -H "Content-Type: application/json" \
    -d '{"query":"test query","limit":5}' &
done
wait
```

**Success Criteria**:
- ✅ All requests complete successfully
- ✅ Response times remain < 1000ms
- ✅ No search failures or timeouts

### Test 3: Search Coverage Validation

**Objective**: Verify that MDDB search covers all expected content

**Test Scenarios**:

**Scenario 1: Collection Coverage**
```
Expected Collections:
- kb-system, kb-development, kb-operations, kb-features
- trade-kb-system, trade-kb-development, trade-kb-operations, trade-kb-features
- ssot-infrastructure, ssot-apps, ssot-general
- chaba-architecture, chaba-assessments, chaba-reports, chaba-implementation, chaba-general
```

**Validation Method**:
```bash
curl -s http://tony-omen.local:11023/v1/vector-stats | jq '.collections'
```

**Success Criteria**:
- ✅ All 13 expected collections present
- ✅ Each collection has expected document count
- ✅ All collections have embedded documents

**Scenario 2: Document Coverage**
```
Expected Documents:
- 154+ total documents across all collections
- 40 SSOT YAML files
- 59 chaba KB files
- 58 trade project files
- 55 chaba documentation files
```

**Validation Method**:
```bash
curl -s http://tony-omen.local:11023/v1/stats | jq '.totalDocuments'
```

**Success Criteria**:
- ✅ Total documents > 150
- ✅ SSOT collection has 40 documents
- ✅ KB collections have expected document counts
- ✅ Chaba docs collections have expected document counts

### Test 4: Integration Validation

**Objective**: Verify that MDDB integration works correctly with other services

**Test Scenarios**:

**Scenario 1: SSOT Auto-Sync Integration**
```
Condition: Edit SSOT YAML file
Expected Behavior:
- File watcher detects change within 2 seconds
- Sync script updates MDDB automatically
- Changes reflected in search results
```

**Validation Method**:
```bash
# 1. Edit SSOT file
echo "# Test change" >> /home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml

# 2. Wait for sync (2-5 seconds)
sleep 5

# 3. Search for the change
curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"Test change","limit":3,"collection":"ssot-infrastructure"}'

# 4. Revert change
git checkout /home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml
```

**Success Criteria**:
- ✅ File watcher detects change within 2 seconds
- ✅ MDDB updated automatically
- ✅ Search results reflect the change
- ✅ Sync service remains healthy

**Scenario 2: MCP Integration**
```
Condition: Use MDDB via MCP interface
Expected Behavior:
- MCP tools respond correctly
- Semantic search works via MCP
- Collection filtering works via MCP
```

**Validation Method**:
```javascript
// Test via MCP interface
mcp_call_tool("mddb", "semantic_search", {
  "collection": "kb-system",
  "query": "GPU memory",
  "top_k": 3
})
```

**Success Criteria**:
- ✅ MCP tools respond without errors
- ✅ Semantic search results returned
- ✅ Collection filtering works correctly
- ✅ Response times acceptable (< 1000ms)

**Scenario 3: Health Monitoring Integration**
```
Condition: MDDB health check via mcp-health
Expected Behavior:
- mcp-health detects MDDB service status
- Health checks include MDDB endpoints
- Dependency tracking works correctly
```

**Validation Method**:
```javascript
// Test health monitoring
mcp_call_tool("mcp-health", "check_health", {})
```

**Success Criteria**:
- ✅ MDDB health status reported
- ✅ All MDDB endpoints checked
- ✅ Dependency tracking functional
- ✅ Recovery actions available

## Automated Testing Framework

### Test Script Structure

```bash
#!/bin/bash
# test-global-rules-and-mddb.sh

echo "=== Testing Global Rules and MDDB Search ==="

# Test 1: MDDB Search Quality
echo "Test 1: MDDB Search Quality"
curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"GPU memory management","limit":5,"collection":"kb-system"}' \
  | jq '.results[0].score'

# Test 2: Search Performance
echo "Test 2: Search Performance"
time curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"health check","limit":5}'

# Test 3: Collection Coverage
echo "Test 3: Collection Coverage"
curl -s http://tony-omen.local:11023/v1/vector-stats | jq '.collections | length'

# Test 4: Document Coverage
echo "Test 4: Document Coverage"
curl -s http://tony-omen.local:11023/v1/stats | jq '.totalDocuments'

# Test 5: SSOT Auto-Sync
echo "Test 5: SSOT Auto-Sync"
systemctl status ssot-sync.service | grep Active

# Test 6: Health Monitoring
echo "Test 6: Health Monitoring"
curl -s http://tony-omen.local:11023/health

echo "=== Testing Complete ==="
```

### Continuous Monitoring

**Metrics to Track**:
- MDDB search response times (p50, p95, p99)
- Search relevance scores (average, median)
- MDDB service uptime and health
- SSOT sync success rate
- MCP tool success rates
- Agent tool selection patterns

**Alert Thresholds**:
- Search response time > 1000ms (warning), > 2000ms (critical)
- Search relevance score < 0.30 (warning), < 0.20 (critical)
- MDDB service health check failure (critical)
- SSOT sync failure (warning)
- MCP tool failure rate > 5% (warning), > 10% (critical)

## Success Criteria Summary

### Global Rules Success
- ✅ 95%+ of documentation queries use MDDB first
- ✅ Appropriate MCP service selection in 90%+ of cases
- ✅ User confirmation obtained before fallback in 100% of cases
- ✅ No silent fallback to traditional tools
- ✅ Service failure detection works correctly

### MDDB Search Success
- ✅ Search relevance scores > 0.45 for top results
- ✅ Search response times < 600ms for 95% of queries
- ✅ All 13 collections present and functional
- ✅ 154+ documents indexed and searchable
- ✅ SSOT auto-sync working correctly
- ✅ MCP integration functional
- ✅ Health monitoring operational

## Related Documentation

- **Global Rules**: /home/tony/.codeium/windsurf/memories/global_rules.md
- **MDDB User Guide**: docs/kb/mddb-user-guide.md
- **Documentation Search**: docs/kb/documentation-search.md
- **MDDB Migration Summary**: docs/kb/mddb-migration-summary.md