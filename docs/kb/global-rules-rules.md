---
category: operations
---

# Testing Global Rules Effectiveness

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

