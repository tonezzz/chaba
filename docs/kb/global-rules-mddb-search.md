---
category: operations
---

# Testing MDDB Search Effectiveness

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

